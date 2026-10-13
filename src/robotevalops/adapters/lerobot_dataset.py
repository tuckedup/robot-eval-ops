"""Read-only inspection of LeRobot-compatible dataset directories + episode-level splits.

Inspection only reads ``meta/info.json`` (and counts files); it never modifies a dataset and does
not import lerobot. The split helper assigns WHOLE episodes to train/eval deterministically; it can
never place adjacent frames of one episode in different splits.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from robotevalops.errors import RobotEvalOpsError
from robotevalops.util import sha256_bytes


def inspect_dataset(path: str | Path) -> dict[str, Any]:
    root = Path(path)
    info_path = root / "meta" / "info.json"
    if not root.is_dir() or not info_path.is_file():
        raise RobotEvalOpsError(
            f"{root} is not a LeRobot-compatible dataset directory (missing meta/info.json)"
        )
    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RobotEvalOpsError(f"{info_path}: invalid JSON: {e}") from e
    feats = info.get("features", {}) if isinstance(info.get("features"), dict) else {}
    episodes_jsonl = root / "meta" / "episodes.jsonl"
    n_ep = info.get("total_episodes")
    if isinstance(n_ep, int) is False and episodes_jsonl.is_file():
        n_ep = sum(1 for line in episodes_jsonl.read_text(encoding="utf-8").splitlines() if line.strip())
    videos = (
        sorted(p.relative_to(root).as_posix() for p in (root / "videos").rglob("*.mp4"))
        if (root / "videos").is_dir()
        else []
    )
    data_files = (
        sorted(p.relative_to(root).as_posix() for p in (root / "data").rglob("*.parquet"))
        if (root / "data").is_dir()
        else []
    )
    return {
        "path": str(root),
        "codebase_version": info.get("codebase_version"),
        "robot_type": info.get("robot_type"),
        "fps": info.get("fps"),
        "total_episodes": n_ep,
        "total_frames": info.get("total_frames"),
        "feature_names": sorted(feats),
        "video_files": len(videos),
        "data_files": len(data_files),
        "provenance": "imported_real_recording",
        "note": (
            "read-only inspection; the repository did not record this dataset and makes no claim "
            "about how it was collected. Splits must be made by whole episode."
        ),
    }


def split_episodes(
    episode_indices: list[int], eval_fraction: float = 0.2, seed: int = 0
) -> dict[str, list[int]]:
    """Deterministic episode-level train/eval split (hash-ranked, whole episodes only)."""
    if not 0.0 < eval_fraction < 1.0:
        raise RobotEvalOpsError("eval_fraction must be in (0, 1)")
    eps = sorted(set(int(e) for e in episode_indices))
    if len(eps) < 2:
        raise RobotEvalOpsError("need at least 2 episodes to make a train/eval split")
    ranked = sorted(eps, key=lambda e: sha256_bytes(f"{seed}|{e}".encode()))
    n_eval = min(len(eps) - 1, max(1, math.floor(eval_fraction * len(eps) + 0.5)))
    ev = sorted(ranked[:n_eval])
    tr = sorted(ranked[n_eval:])
    return {"train": tr, "eval": ev}


def episode_to_trace(
    dataset_root: str | Path, trace_path: str | Path, episode: int | None = None
) -> dict[str, Any]:
    """Write ``trace.jsonl`` (TraceHeader + TraceRow) from a LeRobot dataset episode's parquet.

    Values are copied EXACTLY from the dataset's ``timestamp``, ``observation.state`` and ``action``
    columns; nothing is invented, repaired or reordered. If the parquet cannot be read or a required
    column is missing, NO trace is written and the returned dict says why (``ok`` False).
    State/action names come from ``meta/info.json`` features when present; otherwise they are plain
    positional labels (``observation.state[i]``), which are labels, not data.
    Returns {"ok", "rows", "reason", "episode", "source_files"}.
    """
    from robotevalops.schemas import Provenance, TraceHeader, TraceRow

    root = Path(dataset_root)
    files = sorted((root / "data").rglob("*.parquet")) if (root / "data").is_dir() else []
    if not files:
        return {"ok": False, "rows": 0, "reason": "no data/**/*.parquet files in dataset", "source_files": []}
    try:
        import pandas as pd

        df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    except Exception as e:  # noqa: BLE001 - missing pyarrow, corrupt file, ...
        return {
            "ok": False,
            "rows": 0,
            "reason": f"parquet unreadable: {type(e).__name__}: {e}",
            "source_files": [str(f) for f in files],
        }
    missing = [c for c in ("timestamp", "observation.state", "action") if c not in df.columns]
    if missing:
        return {
            "ok": False,
            "rows": 0,
            "reason": f"missing columns {missing}; trace not written",
            "source_files": [str(f) for f in files],
        }
    if "episode_index" in df.columns:
        ep = int(df["episode_index"].min()) if episode is None else int(episode)
        df = df[df["episode_index"] == ep]
    else:
        ep = 0 if episode is None else int(episode)
    if len(df) == 0:
        return {
            "ok": False,
            "rows": 0,
            "reason": f"episode {ep} has no rows",
            "source_files": [str(f) for f in files],
        }
    info: dict[str, Any] = {}
    info_path = root / "meta" / "info.json"
    if info_path.is_file():
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            info = {}

    def _names(key: str, dim: int) -> list[str]:
        feat = (info.get("features") or {}).get(key) or {}
        names = feat.get("names") if isinstance(feat, dict) else None
        if isinstance(names, dict):  # e.g. {"motors": [...]}
            names = next(iter(names.values()), None)
        if isinstance(names, list) and len(names) == dim:
            return [str(n) for n in names]
        return [f"{key}[{i}]" for i in range(dim)]

    first_state, first_action = list(df["observation.state"].iloc[0]), list(df["action"].iloc[0])
    fps = float(info.get("fps") or 0.0)
    header = TraceHeader(
        state_names=_names("observation.state", len(first_state)),
        action_names=_names("action", len(first_action)),
        fps=fps,
        provenance=Provenance.PHYSICAL_HARDWARE,
    )
    lines = [header.model_dump_json()]
    for i, (_, r) in enumerate(df.iterrows()):
        row = TraceRow(
            i=i,
            t=float(r["timestamp"]),
            state=[float(x) for x in r["observation.state"]],
            action=[float(x) for x in r["action"]],
        )
        lines.append(json.dumps(row.model_dump(), allow_nan=True))
    Path(trace_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "rows": len(df),
        "reason": None,
        "episode": ep,
        "source_files": [str(f) for f in files],
    }
