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
