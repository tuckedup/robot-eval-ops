"""Read-only inspection of LeRobot-compatible dataset directories + episode-level splits.

Layout support is VERSION-DISPATCHED (see docs/lerobot-datasets.md):
  * v3.0  : ``meta/episodes/chunk-*/file-*.parquet`` per-episode metadata; many episodes share one
            ``data/chunk-*/file-*.parquet`` shard and one ``videos/<camera>/chunk-*/file-*.mp4`` per camera.
  * v2.0/2.1: ``meta/episodes.jsonl``; one parquet + one mp4 per episode.
Episode ids are the dataset's ACTUAL ids (they need not be 0..n-1) and an episode's rows/frames are selected
by its metadata (shard path, index range, video window), never by guessing.

Nothing here modifies a dataset, imports lerobot, or invents data. The split helper assigns WHOLE episodes to
train/eval deterministically.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from robotevalops.errors import RobotEvalOpsError
from robotevalops.util import sha256_bytes

SUPPORTED_VERSIONS = ("v2.0", "v2.1", "v3.0")
# Writer whose on-disk layout the readers and fixtures were checked against (docs/lerobot-datasets.md).
TESTED_LEROBOT_VERSION = "0.4.4"
_V2_DATA_PATH = "data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet"
_V2_VIDEO_PATH = "videos/chunk-{episode_chunk:03d}/{video_key}/episode_{episode_index:06d}.mp4"
_V3_DATA_PATH = "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet"
_V3_VIDEO_PATH = "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4"


@dataclass(frozen=True)
class VideoRef:
    """Where one camera's frames for one episode live. In v3 many episodes share one mp4; the episode is the
    [from_timestamp, to_timestamp) window inside it. In v2 each episode has its own file (from=0)."""

    key: str
    relpath: str | None
    from_timestamp: float | None
    to_timestamp: float | None


@dataclass
class EpisodeMeta:
    episode_index: int  # the dataset's ACTUAL id
    length: int | None
    data_relpath: str | None
    dataset_from_index: int | None = None
    dataset_to_index: int | None = None
    videos: dict[str, VideoRef] = field(default_factory=dict)


@dataclass
class EpisodeTable:
    layout: str  # "v3" | "v2" | "none"
    version: str | None  # codebase_version as declared (None if inferred; see problems)
    episodes: list[EpisodeMeta] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ids(self) -> list[int]:
        return [e.episode_index for e in self.episodes]

    def get(self, episode_index: int) -> EpisodeMeta | None:
        return next((e for e in self.episodes if e.episode_index == episode_index), None)


def video_keys(info: dict[str, Any]) -> list[str]:
    feats = info.get("features")
    if not isinstance(feats, dict):
        return []
    return sorted(k for k, v in feats.items() if isinstance(v, dict) and v.get("dtype") == "video")


def _num(v: Any) -> Any:
    if v is None:
        return None
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def _int_or_none(v: Any) -> int | None:
    v = _num(v)
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
        return None
    return int(v) if float(v).is_integer() else None


def _float_or_none(v: Any) -> float | None:
    v = _num(v)
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) else None


def _fmt(template: str, **kw: Any) -> str | None:
    try:
        return template.format(**kw)
    except (KeyError, IndexError, ValueError):
        return None


def detect_version(root: Path, info: dict[str, Any]) -> tuple[str | None, str, list[str]]:
    """(declared version, layout family, problems). A declared codebase_version wins; otherwise the layout is
    inferred from which episode metadata exists and the inference is reported (never silent)."""
    declared = info.get("codebase_version")
    if isinstance(declared, str) and declared:
        for fam, prefix in (("v3", "v3."), ("v2", "v2.")):
            if declared.startswith(prefix):
                if declared not in SUPPORTED_VERSIONS:
                    return declared, "none", [f"codebase_version {declared!r} not in {SUPPORTED_VERSIONS}"]
                return declared, fam, []
        return (
            declared,
            "none",
            [f"unsupported codebase_version {declared!r}; supported: {SUPPORTED_VERSIONS}"],
        )
    ep_dir = root / "meta" / "episodes"
    if ep_dir.is_dir() and any(ep_dir.rglob("*.parquet")):
        return (
            None,
            "v3",
            ["no codebase_version in info.json; layout inferred as v3 (meta/episodes/*.parquet)"],
        )
    if (root / "meta").is_dir() and any((root / "meta").glob("episodes*.jsonl")):
        return None, "v2", ["no codebase_version in info.json; layout inferred as v2 (meta/episodes.jsonl)"]
    return None, "none", ["no codebase_version in info.json and no per-episode metadata found"]


def load_episode_table(root: str | Path, info: dict[str, Any] | None = None) -> EpisodeTable:
    """Per-episode metadata with version dispatch. Never raises on malformed data: problems are returned so QA
    can flag them. Returns actual episode ids, lengths, shard paths, global index ranges, camera windows."""
    root = Path(root)
    if info is None:
        try:
            info = json.loads((root / "meta" / "info.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            return EpisodeTable("none", None, problems=[f"meta/info.json unreadable: {e}"])
    version, family, problems = detect_version(root, info)
    table = EpisodeTable(family, version, problems=list(problems))
    cams = video_keys(info)
    if family == "v3":
        _load_v3(root, info, cams, table)
    elif family == "v2":
        _load_v2(root, info, cams, table)
    return table


def _load_v3(root: Path, info: dict[str, Any], cams: list[str], table: EpisodeTable) -> None:
    ep_dir = root / "meta" / "episodes"
    files = sorted(ep_dir.rglob("*.parquet")) if ep_dir.is_dir() else []
    if not files:
        table.problems.append("no meta/episodes/chunk-*/file-*.parquet found (v3 per-episode metadata)")
        return
    try:
        import pandas as pd

        df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    except Exception as e:  # noqa: BLE001 - corrupt parquet / missing pyarrow is a QA finding
        table.problems.append(f"episode metadata parquet unreadable: {type(e).__name__}: {e}")
        return
    table.source_files = [f.relative_to(root).as_posix() for f in files]
    data_tpl = info["data_path"] if isinstance(info.get("data_path"), str) else _V3_DATA_PATH
    vid_tpl = info["video_path"] if isinstance(info.get("video_path"), str) else _V3_VIDEO_PATH
    need = [
        "episode_index",
        "length",
        "data/chunk_index",
        "data/file_index",
        "dataset_from_index",
        "dataset_to_index",
    ]
    absent = [c for c in need if c not in df.columns]
    if absent:
        table.problems.append(f"episode metadata lacks columns {absent}")
    if "episode_index" not in df.columns:
        return
    for rec in df.to_dict("records"):
        ep = _int_or_none(rec.get("episode_index"))
        if ep is None:
            table.problems.append(
                f"episode metadata row with non-integer episode_index {rec.get('episode_index')!r}"
            )
            continue
        ci, fi = _int_or_none(rec.get("data/chunk_index")), _int_or_none(rec.get("data/file_index"))
        data_rel = (
            _fmt(data_tpl, chunk_index=ci, file_index=fi) if ci is not None and fi is not None else None
        )
        vids: dict[str, VideoRef] = {}
        for k in cams:
            vc = _int_or_none(rec.get(f"videos/{k}/chunk_index"))
            vf = _int_or_none(rec.get(f"videos/{k}/file_index"))
            rel = (
                _fmt(vid_tpl, video_key=k, chunk_index=vc, file_index=vf)
                if vc is not None and vf is not None
                else None
            )
            vids[k] = VideoRef(
                k,
                rel,
                _float_or_none(rec.get(f"videos/{k}/from_timestamp")),
                _float_or_none(rec.get(f"videos/{k}/to_timestamp")),
            )
        table.episodes.append(
            EpisodeMeta(
                ep,
                _int_or_none(rec.get("length")),
                data_rel,
                _int_or_none(rec.get("dataset_from_index")),
                _int_or_none(rec.get("dataset_to_index")),
                vids,
            )
        )


def _load_v2(root: Path, info: dict[str, Any], cams: list[str], table: EpisodeTable) -> None:
    meta = root / "meta"
    files = sorted(meta.glob("episodes*.jsonl")) if meta.is_dir() else []
    if not files:
        table.problems.append("no meta/episodes.jsonl found (v2.x per-episode metadata)")
        return
    table.source_files = [f.relative_to(root).as_posix() for f in files]
    cs = info.get("chunks_size")
    chunk_size = cs if isinstance(cs, int) and cs > 0 else 1000
    fps = _float_or_none(info.get("fps"))
    data_tpl = info["data_path"] if isinstance(info.get("data_path"), str) else _V2_DATA_PATH
    vid_tpl = info["video_path"] if isinstance(info.get("video_path"), str) else _V2_VIDEO_PATH
    for f in files:
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                table.problems.append(f"{f.name}:{n} invalid JSON: {e}")
                continue
            ep = _int_or_none(rec.get("episode_index")) if isinstance(rec, dict) else None
            if ep is None:
                table.problems.append(f"{f.name}:{n} has no integer episode_index")
                continue
            kw = {"episode_chunk": ep // chunk_size, "episode_index": ep}
            length = _int_or_none(rec.get("length"))
            end = length / fps if length is not None and fps else None
            vids = {k: VideoRef(k, _fmt(vid_tpl, video_key=k, **kw), 0.0, end) for k in cams}
            table.episodes.append(EpisodeMeta(ep, length, _fmt(data_tpl, **kw), None, None, vids))


def read_episode_rows(root: str | Path, ep: EpisodeMeta) -> Any:
    """DataFrame holding ONLY this episode's rows, read from its declared shard, in file order."""
    import pyarrow.parquet as pq

    if ep.data_relpath is None:
        raise RobotEvalOpsError(f"episode {ep.episode_index} has no resolvable data file")
    path = Path(root) / ep.data_relpath
    if "episode_index" in set(pq.read_schema(path).names):
        tbl = pq.read_table(path, filters=[("episode_index", "=", ep.episode_index)])
    else:
        tbl = pq.read_table(path)
    return tbl.to_pandas()


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
    table = load_episode_table(root, info)
    n_ep = info.get("total_episodes")
    if isinstance(n_ep, int) is False and table.episodes:
        n_ep = len(table.episodes)
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
        "layout": table.layout,
        "robot_type": info.get("robot_type"),
        "fps": info.get("fps"),
        "total_episodes": n_ep,
        "total_frames": info.get("total_frames"),
        "episode_ids": table.ids,
        "cameras": video_keys(info),
        "feature_names": sorted(feats),
        "video_files": len(videos),
        "data_files": len(data_files),
        "metadata_problems": table.problems,
        "provenance": "imported_real_recording",
        "note": (
            "read-only inspection ONLY (no content QA); this repo did not record the dataset; no "
            "claim about how it was collected. Splits must be made by whole episode."
        ),
    }


def split_episodes(
    episode_indices: list[int], eval_fraction: float = 0.2, seed: int = 0
) -> dict[str, list[int]]:
    """Deterministic episode-level train/eval split (hash-ranked, whole episodes): the only split helper."""
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
    """Write ``trace.jsonl`` (TraceHeader + TraceRow) for ONE dataset episode.

    With per-episode metadata (v3 parquet / v2 jsonl) the requested episode's ACTUAL id selects its shard and
    only its rows are read; an id absent from the metadata is refused (nothing written). Without metadata
    (loose legacy parquet) rows are selected by the ``episode_index`` column. Values are copied EXACTLY from
    ``timestamp``/``observation.state``/``action``; nothing is invented, repaired or reordered. If the data
    cannot be read or a column is missing, NO trace is written and ``ok`` is False with the reason.
    Returns {"ok", "rows", "reason", "episode", "source_files"}.
    """
    from robotevalops.schemas import Provenance, TraceHeader, TraceRow

    root = Path(dataset_root)
    files = sorted((root / "data").rglob("*.parquet")) if (root / "data").is_dir() else []
    if not files:
        return {"ok": False, "rows": 0, "reason": "no data/**/*.parquet files in dataset", "source_files": []}
    srcs = [str(f) for f in files]
    info: dict[str, Any] = {}
    info_path = root / "meta" / "info.json"
    if info_path.is_file():
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            info = {}
    try:
        import pandas as pd

        table = load_episode_table(root, info) if info else EpisodeTable("none", None)
        if table.episodes:
            meta_ep = table.get(min(table.ids) if episode is None else int(episode))
            if meta_ep is None:
                return {
                    "ok": False,
                    "rows": 0,
                    "reason": f"episode {episode} is not in the dataset metadata "
                    f"(available: {sorted(table.ids)}); trace not written",
                    "source_files": srcs,
                }
            ep = meta_ep.episode_index
            df = read_episode_rows(root, meta_ep)
            srcs = [str(root / str(meta_ep.data_relpath))]
        else:
            df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
            ep = 0
    except Exception as e:  # noqa: BLE001 - missing pyarrow, corrupt file, ...
        return {
            "ok": False,
            "rows": 0,
            "reason": f"parquet unreadable: {type(e).__name__}: {e}",
            "source_files": srcs,
        }
    missing = [c for c in ("timestamp", "observation.state", "action") if c not in df.columns]
    if missing:
        return {
            "ok": False,
            "rows": 0,
            "reason": f"missing columns {missing}; trace not written",
            "source_files": srcs,
        }
    if not table.episodes:  # legacy loose layout: select by column
        if "episode_index" in df.columns:
            ep = int(df["episode_index"].min()) if episode is None else int(episode)
            df = df[df["episode_index"] == ep]
        else:
            ep = 0 if episode is None else int(episode)
    if len(df) == 0:
        return {"ok": False, "rows": 0, "reason": f"episode {ep} has no rows", "source_files": srcs}

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
    return {"ok": True, "rows": len(df), "reason": None, "episode": ep, "source_files": srcs}
