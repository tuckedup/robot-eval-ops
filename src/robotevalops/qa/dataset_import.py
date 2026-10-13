"""Read-only QA of a small LeRobot-style dataset directory (meta/info.json, meta/episodes*, data/*.parquet,
videos/). Never modifies the dataset. Parquet checks need pyarrow (pandas engine); without it they are
skipped and the report says so explicitly."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from robotevalops.schemas import QACode, QAFlag, Severity


@dataclass
class DatasetReport:
    root: str
    info: dict[str, Any] = field(default_factory=dict)
    episode_count: int | None = None
    total_frames: int | None = None
    fps: float | None = None
    feature_names: list[str] = field(default_factory=list)
    parquet_files: list[str] = field(default_factory=list)
    video_files: list[str] = field(default_factory=list)
    parquet_checked: bool = False
    notes: list[str] = field(default_factory=list)
    flags: list[QAFlag] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(f.severity == Severity.ERROR for f in self.flags)


def _flag(code: QACode, sev: Severity, msg: str, subject: str = "", **ev: Any) -> QAFlag:
    return QAFlag(code=code, severity=sev, message=msg, subject=subject, evidence=ev)


def _read_episodes(meta: Path) -> list[dict[str, Any]]:
    eps: list[dict[str, Any]] = []
    for p in sorted(meta.glob("episodes*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                eps.append(json.loads(line))
    return eps


def qa_lerobot_dataset(root: str | Path) -> DatasetReport:
    r = Path(root)
    rep = DatasetReport(root=str(r))
    info_p = r / "meta" / "info.json"
    if not info_p.is_file():
        rep.flags.append(
            _flag(
                QACode.MISSING_ARTIFACT,
                Severity.ERROR,
                "meta/info.json is missing; this is not a LeRobot-style dataset root",
                "meta/info.json",
                relpath="meta/info.json",
            )
        )
        return rep
    try:
        rep.info = json.loads(info_p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        rep.flags.append(
            _flag(
                QACode.SCHEMA_MISMATCH,
                Severity.ERROR,
                f"meta/info.json is not valid JSON: {exc}",
                "meta/info.json",
            )
        )
        return rep
    info = rep.info
    rep.fps = float(info["fps"]) if isinstance(info.get("fps"), int | float) else None
    feats = info.get("features")
    rep.feature_names = sorted(feats) if isinstance(feats, dict) else []
    for key in ("fps", "features"):
        if key not in info:
            rep.flags.append(
                _flag(
                    QACode.MISSING_FIELD,
                    Severity.ERROR,
                    f"meta/info.json lacks {key!r}",
                    "meta/info.json",
                    field=key,
                )
            )
    eps = _read_episodes(r / "meta")
    if not eps:
        rep.flags.append(
            _flag(
                QACode.MISSING_ARTIFACT,
                Severity.ERROR,
                "no meta/episodes*.jsonl entries found",
                "meta/episodes.jsonl",
            )
        )
    rep.episode_count = len(eps) if eps else info.get("total_episodes")
    ep_lengths = [e.get("length") for e in eps]
    int_lengths = [x for x in ep_lengths if isinstance(x, int)]
    if eps and len(int_lengths) == len(ep_lengths):
        rep.total_frames = sum(int_lengths)
    elif isinstance(info.get("total_frames"), int):
        rep.total_frames = info["total_frames"]
    if eps and isinstance(info.get("total_episodes"), int) and info["total_episodes"] != len(eps):
        rep.flags.append(
            _flag(
                QACode.SCHEMA_MISMATCH,
                Severity.ERROR,
                f"info.json total_episodes={info['total_episodes']} but meta lists {len(eps)} episodes",
                "meta/info.json",
            )
        )
    if (
        rep.total_frames is not None
        and isinstance(info.get("total_frames"), int)
        and info["total_frames"] != rep.total_frames
    ):
        rep.flags.append(
            _flag(
                QACode.SCHEMA_MISMATCH,
                Severity.ERROR,
                f"info.json total_frames={info['total_frames']} but episode lengths sum to "
                f"{rep.total_frames}",
                "meta/info.json",
            )
        )
    ids: list[int] = [e["episode_index"] for e in eps if isinstance(e.get("episode_index"), int)]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        rep.flags.append(
            _flag(
                QACode.DUPLICATE_ID,
                Severity.ERROR,
                f"duplicate episode_index values in meta: {dup}",
                "meta/episodes.jsonl",
            )
        )
    rep.parquet_files = sorted(p.relative_to(r).as_posix() for p in (r / "data").rglob("*.parquet"))
    rep.video_files = sorted(p.relative_to(r).as_posix() for p in (r / "videos").rglob("*.mp4"))
    if not rep.parquet_files:
        rep.flags.append(
            _flag(QACode.MISSING_ARTIFACT, Severity.ERROR, "no data/*.parquet files found", "data/")
        )
    if not rep.video_files:
        rep.flags.append(
            _flag(
                QACode.MISSING_VIDEO,
                Severity.WARNING,
                "no videos/*.mp4 found (state-only dataset, or videos were not copied)",
                "videos/",
            )
        )
    _check_parquet(r, rep, set(i for i in ids if isinstance(i, int)))
    return rep


def _check_parquet(r: Path, rep: DatasetReport, meta_ids: set[int]) -> None:
    try:
        import pandas as pd
        import pyarrow  # noqa: F401
    except ImportError:
        rep.notes.append("pandas/pyarrow not installed: parquet content NOT checked (existence only)")
        return
    rep.parquet_checked = True
    frames = 0
    seen_eps: set[int] = set()
    for rel in rep.parquet_files:
        try:
            df = pd.read_parquet(r / rel)
        except Exception as exc:  # unreadable file is a QA finding, not a crash
            rep.flags.append(
                _flag(
                    QACode.UNDECODABLE_FRAMES,
                    Severity.ERROR,
                    f"{rel} cannot be read as parquet: {exc}",
                    rel,
                    relpath=rel,
                )
            )
            continue
        frames += len(df)
        for c in ("episode_index", "timestamp"):
            if c not in df.columns:
                rep.flags.append(
                    _flag(
                        QACode.MISSING_FIELD,
                        Severity.ERROR,
                        f"{rel} lacks column {c!r}",
                        rel,
                        relpath=rel,
                        field=c,
                    )
                )
        if "episode_index" not in df.columns or "timestamp" not in df.columns:
            continue
        for ep, g in df.groupby("episode_index", sort=True):
            ep_i = int(str(ep))
            seen_eps.add(ep_i)
            ts = g["timestamp"].to_numpy(dtype=float)
            bad = [i for i in range(1, len(ts)) if not ts[i] >= ts[i - 1]]
            if bad:
                rep.flags.append(
                    _flag(
                        QACode.NONMONOTONIC_TIMESTAMPS,
                        Severity.ERROR,
                        f"{rel}: episode {ep} timestamps decrease/non-finite at row offset {bad[0]}",
                        rel,
                        relpath=rel,
                        episode=ep_i,
                        first_index=bad[0],
                    )
                )
    if rep.total_frames is not None and frames != rep.total_frames:
        rep.flags.append(
            _flag(
                QACode.LOW_COMPLETENESS,
                Severity.ERROR,
                f"parquet rows total {frames} but meta says {rep.total_frames} frames",
                "data/",
                parquet_rows=frames,
                meta_frames=rep.total_frames,
            )
        )
    missing = sorted(meta_ids - seen_eps)
    if meta_ids and missing:
        rep.flags.append(
            _flag(
                QACode.MISSING_ARTIFACT,
                Severity.ERROR,
                f"episodes listed in meta but absent from parquet: {missing}",
                "data/",
            )
        )


def split_episodes(
    episode_ids: list[int], *, seed: int, val_fraction: float = 0.2
) -> tuple[list[int], list[int]]:
    """Deterministic episode-level split: whole episodes only, never frames. Returns (train, val), sorted.
    With >=2 episodes and val_fraction>0 at least one episode goes to each side."""
    ids = sorted(set(episode_ids))
    if len(ids) != len(episode_ids):
        raise ValueError("duplicate episode ids")
    rng = random.Random(seed)
    shuffled = ids[:]
    rng.shuffle(shuffled)
    n_val = round(len(ids) * val_fraction)
    if len(ids) >= 2 and val_fraction > 0:
        n_val = min(max(n_val, 1), len(ids) - 1)
    return sorted(shuffled[n_val:]), sorted(shuffled[:n_val])
