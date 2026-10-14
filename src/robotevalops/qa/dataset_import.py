"""Read-only content QA of a LeRobot dataset directory (v2.x and v3.0 layouts). Never modifies the dataset.

This is the acceptance check for *imported demonstrations*, so it is deliberately strict:

* layout: supported ``codebase_version``, per-episode metadata readable, unique ACTUAL episode ids,
  declared totals consistent with the metadata;
* data: every episode's rows come from its declared shard; ``action`` and ``observation.state`` exist, are
  numeric vectors of the declared width and finite; ``timestamp`` is finite and strictly increasing within the
  episode; ``frame_index`` is 0..n-1; row count equals the declared length; the global ``index`` matches
  ``dataset_from_index/dataset_to_index`` and ranges are contiguous across shard boundaries;
* cameras: every episode x camera video file exists, DECODES, its window lies inside the file and holds the
  expected number of frames at the expected times (alignment with the state/action rows).

The verdict is one of ``status``:
  rejected   - at least one error flag (``accepted_episodes`` still lists episodes with no error of their own)
  incomplete - no error found but a criterion could not be verified (no pyarrow, no video decoder, state-only
               dataset, decode budget exceeded). This is NEVER reported as accepted.
  accepted   - every criterion ran and passed, including cameras (the video-backed demonstration rubric)
  accepted_state_only - every non-video criterion passed and the caller explicitly set ``require_video=False``
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from robotevalops.adapters.lerobot_dataset import (
    SUPPORTED_VERSIONS,
    EpisodeMeta,
    EpisodeTable,
    VideoRef,
    load_episode_table,
    read_episode_rows,
    video_keys,
)
from robotevalops.schemas import QACode, QAFlag, Severity

PASS, FAIL, SKIPPED = "pass", "fail", "skipped"
CRITERIA = (
    "layout_supported",
    "info_valid",
    "episode_metadata",
    "data_readable",
    "state_action_schema",
    "values_finite",
    "timestamps",
    "frame_consistency",
    "index_continuity",
    "video_present",
    "video_decodable",
    "video_alignment",
)


@dataclass
class DatasetReport:
    root: str
    info: dict[str, Any] = field(default_factory=dict)
    codebase_version: str | None = None
    layout: str = "none"
    episode_ids: list[int] = field(default_factory=list)
    scored_episodes: list[int] = field(default_factory=list)  # episodes whose rows/frames were actually read
    episode_count: int | None = None
    total_frames: int | None = None
    fps: float | None = None
    cameras: list[str] = field(default_factory=list)
    feature_names: list[str] = field(default_factory=list)
    parquet_files: list[str] = field(default_factory=list)
    video_files: list[str] = field(default_factory=list)
    parquet_checked: bool = False
    videos_decoded: int = 0
    criteria: dict[str, str] = field(default_factory=lambda: {c: SKIPPED for c in CRITERIA})
    skipped_reasons: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    flags: list[QAFlag] = field(default_factory=list)
    require_video: bool = True

    @property
    def ok(self) -> bool:
        """No error flag. NOT the same as accepted: see ``status`` (incomplete checks are ok, unaccepted)."""
        return not any(f.severity == Severity.ERROR for f in self.flags)

    @property
    def rejected_episodes(self) -> list[int]:
        return sorted(
            {
                int(f.subject.split(":", 1)[1])
                for f in self.flags
                if f.severity == Severity.ERROR and f.subject.startswith("episode:")
            }
        )

    @property
    def dataset_level_errors(self) -> bool:
        return any(f.severity == Severity.ERROR and not f.subject.startswith("episode:") for f in self.flags)

    @property
    def accepted_episodes(self) -> list[int]:
        """Episodes with no error of their own. Empty unless dataset-level checks also hold."""
        if self.dataset_level_errors or self.status == "incomplete":
            return []
        bad = set(self.rejected_episodes)
        return [e for e in self.scored_episodes if e not in bad]

    @property
    def status(self) -> str:
        if not self.ok:
            return "rejected"
        required = [c for c in CRITERIA if c not in ("video_present", "video_decodable", "video_alignment")]
        video = ["video_present", "video_decodable", "video_alignment"]
        if any(self.criteria[c] != PASS for c in required):
            return "incomplete"
        if all(self.criteria[c] == PASS for c in video):
            return "accepted"
        if not self.cameras and not self.require_video:
            return "accepted_state_only"
        return "incomplete"

    @property
    def accepted(self) -> bool:
        return self.status in ("accepted", "accepted_state_only")

    @property
    def status_reasons(self) -> list[str]:
        """Actionable reasons for any non-accepted status."""
        out = [f"{f.code.value}: {f.message}" for f in self.flags if f.severity == Severity.ERROR]
        out += [
            f"not verified: {c} ({r})" for c, r in self.skipped_reasons.items() if self.criteria[c] == SKIPPED
        ]
        if self.status == "incomplete" and not self.cameras:
            out.append(
                "no camera features: state-only data cannot meet the video-backed demonstration rubric"
            )
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "status": self.status,
            "accepted": self.accepted,
            "codebase_version": self.codebase_version,
            "layout": self.layout,
            "episode_ids": self.episode_ids,
            "scored_episodes": self.scored_episodes,
            "accepted_episodes": self.accepted_episodes,
            "rejected_episodes": self.rejected_episodes,
            "episode_count": self.episode_count,
            "total_frames": self.total_frames,
            "fps": self.fps,
            "cameras": self.cameras,
            "criteria": self.criteria,
            "skipped_reasons": self.skipped_reasons,
            "videos_decoded": self.videos_decoded,
            "reasons": self.status_reasons,
            "notes": self.notes,
            "flags": [f.model_dump(mode="json") for f in self.flags],
        }


def _flag(code: QACode, sev: Severity, msg: str, subject: str = "", **ev: Any) -> QAFlag:
    return QAFlag(code=code, severity=sev, message=msg, subject=subject, evidence=ev)


class _Ctx:
    """Tracks per-criterion state: a criterion is PASS only if it ran and nothing failed it."""

    def __init__(self, rep: DatasetReport) -> None:
        self.rep = rep
        self.failed: set[str] = set()
        self.ran: set[str] = set()

    def ran_(self, crit: str) -> None:
        self.ran.add(crit)

    def error(self, crit: str, code: QACode, msg: str, subject: str = "", **ev: Any) -> None:
        self.failed.add(crit)
        self.ran.add(crit)
        self.rep.flags.append(_flag(code, Severity.ERROR, msg, subject, criterion=crit, **ev))

    def skip(self, crit: str, why: str) -> None:
        self.rep.skipped_reasons.setdefault(crit, why)

    def finish(self) -> None:
        for c in CRITERIA:
            if c in self.failed:
                self.rep.criteria[c] = FAIL
            elif c in self.ran and c not in self.rep.skipped_reasons:
                self.rep.criteria[c] = PASS
            else:
                self.rep.criteria[c] = SKIPPED


def qa_lerobot_dataset(
    root: str | Path,
    *,
    episodes: list[int] | None = None,
    require_video: bool = True,
    decode_videos: bool = True,
    max_decode_frames: int = 100_000,
    frame_tolerance: int = 1,
) -> DatasetReport:
    """QA the dataset (or only ``episodes``: only those episodes' rows/frames are read and scored).

    ``require_video=False`` lets a state-only dataset reach ``accepted_state_only``; it is never ``accepted``.
    ``frame_tolerance`` is the allowed |decoded frames - length| per camera window.
    """
    r = Path(root)
    rep = DatasetReport(root=str(r), require_video=require_video)
    ctx = _Ctx(rep)
    info_p = r / "meta" / "info.json"
    if not info_p.is_file():
        ctx.error(
            "info_valid",
            QACode.MISSING_ARTIFACT,
            "meta/info.json is missing; this is not a LeRobot-style dataset root",
            "meta/info.json",
            relpath="meta/info.json",
        )
        ctx.finish()
        return rep
    try:
        rep.info = json.loads(info_p.read_text(encoding="utf-8"))
        if not isinstance(rep.info, dict):
            raise ValueError("top-level JSON value is not an object")
    except (json.JSONDecodeError, ValueError) as exc:
        rep.info = {}
        ctx.error(
            "info_valid", QACode.SCHEMA_MISMATCH, f"meta/info.json is not valid JSON: {exc}", "meta/info.json"
        )
        ctx.finish()
        return rep
    info = rep.info
    _check_info(rep, ctx)
    table = load_episode_table(r, info)
    rep.layout, rep.codebase_version = table.layout, table.version
    _check_layout_and_episodes(rep, ctx, table)
    feats: dict[str, Any] = info["features"] if isinstance(info.get("features"), dict) else {}
    rep.feature_names = sorted(feats)
    rep.cameras = video_keys(info)
    rep.parquet_files = sorted(p.relative_to(r).as_posix() for p in (r / "data").rglob("*.parquet"))
    rep.video_files = sorted(p.relative_to(r).as_posix() for p in (r / "videos").rglob("*.mp4"))
    if not rep.parquet_files:
        ctx.error("data_readable", QACode.MISSING_ARTIFACT, "no data/**/*.parquet files found", "data/")
    selected = table.episodes
    if episodes is not None:
        wanted = set(episodes)
        unknown = sorted(wanted - set(table.ids))
        if unknown:
            ctx.error(
                "episode_metadata",
                QACode.MISSING_ARTIFACT,
                f"requested episode(s) {unknown} are not in the dataset metadata "
                f"(actual ids: {sorted(table.ids)})",
                "meta/episodes",
            )
        selected = [e for e in table.episodes if e.episode_index in wanted]
        rep.notes.append(f"QA restricted to episodes {sorted(wanted)}; other episodes were not read")
    rep.scored_episodes = sorted(e.episode_index for e in selected)
    if table.episodes and rep.parquet_files:
        _check_data(r, rep, ctx, selected, feats, partial=episodes is not None)
    if rep.cameras:
        _check_videos(r, rep, ctx, selected, decode_videos, max_decode_frames, frame_tolerance)
    elif require_video:
        for c in ("video_present", "video_decodable", "video_alignment"):
            ctx.skip(c, "dataset declares no camera (dtype 'video') features")
    else:
        rep.notes.append(
            "state-only dataset accepted by explicit require_video=False; no camera evidence exists"
        )
    ctx.finish()
    if not rep.cameras and not require_video:
        for c in ("video_present", "video_decodable", "video_alignment"):
            rep.criteria[c] = SKIPPED
    return rep


def _check_info(rep: DatasetReport, ctx: _Ctx) -> None:
    info = rep.info
    ctx.ran_("info_valid")
    for key in ("fps", "features"):
        if key not in info:
            ctx.error(
                "info_valid",
                QACode.MISSING_FIELD,
                f"meta/info.json lacks {key!r}",
                "meta/info.json",
                field=key,
            )
    fps = info.get("fps")
    if isinstance(fps, bool) or not isinstance(fps, int | float) or not math.isfinite(fps) or fps <= 0:
        if "fps" in info:
            ctx.error(
                "info_valid",
                QACode.SCHEMA_MISMATCH,
                f"info.json fps={fps!r} is not a positive number",
                "meta/info.json",
            )
    else:
        rep.fps = float(fps)
    feats = info.get("features")
    if isinstance(feats, dict):
        for k in ("action", "observation.state"):
            f = feats.get(k)
            if not isinstance(f, dict):
                ctx.error(
                    "info_valid",
                    QACode.MISSING_FIELD,
                    f"info.json features lacks {k!r}; demonstration QA needs state and action",
                    "meta/info.json",
                    field=k,
                )
                continue
            shape = f.get("shape")
            ok_shape = (
                isinstance(shape, list | tuple)
                and len(shape) == 1
                and isinstance(shape[0], int)
                and shape[0] > 0
            )
            if not ok_shape or not str(f.get("dtype", "")).startswith(("float", "int")):
                ctx.error(
                    "info_valid",
                    QACode.SCHEMA_MISMATCH,
                    f"feature {k!r} must be a 1-D numeric vector (shape [n], dtype float/int); "
                    f"got shape={shape!r} dtype={f.get('dtype')!r}",
                    "meta/info.json",
                    field=k,
                )
    elif "features" in info:
        ctx.error(
            "info_valid", QACode.SCHEMA_MISMATCH, "info.json 'features' is not an object", "meta/info.json"
        )


def _check_layout_and_episodes(rep: DatasetReport, ctx: _Ctx, table: EpisodeTable) -> None:
    info = rep.info
    ctx.ran_("layout_supported")
    if table.layout == "none" or (table.version is not None and table.version not in SUPPORTED_VERSIONS):
        ctx.error(
            "layout_supported",
            QACode.SCHEMA_MISMATCH,
            "; ".join(table.problems) or "unrecognised dataset layout",
            "meta/info.json",
            supported=list(SUPPORTED_VERSIONS),
        )
        return
    if table.version is None:
        rep.notes.append("; ".join(table.problems))  # inferred layout: usable, but disclosed
        ctx.skip("layout_supported", "codebase_version absent from info.json; layout was inferred")
    ctx.ran_("episode_metadata")
    for p in table.problems:
        if "inferred" not in p:
            ctx.error("episode_metadata", QACode.MISSING_ARTIFACT, p, "meta/episodes")
    eps = table.episodes
    if not eps:
        if not table.problems:
            ctx.error(
                "episode_metadata",
                QACode.MISSING_ARTIFACT,
                "per-episode metadata lists no episodes",
                "meta/episodes",
            )
        return
    rep.episode_ids = sorted(table.ids)
    rep.episode_count = len(eps)
    dup = sorted({i for i in table.ids if table.ids.count(i) > 1})
    if dup:
        ctx.error(
            "episode_metadata",
            QACode.DUPLICATE_ID,
            f"duplicate episode_index values in metadata: {dup}",
            "meta/episodes",
        )
    bad_len = [e.episode_index for e in eps if e.length is None or e.length <= 0]
    for ep in bad_len:
        ctx.error(
            "episode_metadata",
            QACode.SCHEMA_MISMATCH,
            f"episode {ep} has a missing/non-positive length in metadata",
            f"episode:{ep}",
        )
    lengths = [e.length for e in eps if e.length is not None]
    if len(lengths) == len(eps):
        rep.total_frames = sum(lengths)
    te, tf = info.get("total_episodes"), info.get("total_frames")
    if isinstance(te, int) and te != len(eps):
        ctx.error(
            "episode_metadata",
            QACode.SCHEMA_MISMATCH,
            f"info.json total_episodes={te} but metadata lists {len(eps)} episodes",
            "meta/info.json",
        )
    if rep.total_frames is not None and isinstance(tf, int) and tf != rep.total_frames:
        ctx.error(
            "episode_metadata",
            QACode.SCHEMA_MISMATCH,
            f"info.json total_frames={tf} but episode lengths sum to {rep.total_frames}",
            "meta/info.json",
        )


def _finite_vec_col(series: Any, width: int | None) -> tuple[Any, str | None]:
    """(2-D float array | None, problem). Rejects ragged/non-numeric/wrong-width values."""
    import numpy as np

    try:
        arr = np.stack([np.asarray(v, dtype=float) for v in series.to_list()])
    except (ValueError, TypeError) as exc:
        return None, f"values are not uniform numeric vectors ({exc})"
    if arr.ndim != 2:
        return None, f"values are not 1-D vectors (array ndim={arr.ndim})"
    if width is not None and arr.shape[1] != width:
        return None, f"vector width {arr.shape[1]} != declared {width}"
    return arr, None


def _check_data(
    root: Path,
    rep: DatasetReport,
    ctx: _Ctx,
    selected: list[EpisodeMeta],
    feats: dict[str, Any],
    *,
    partial: bool,
) -> None:
    try:
        import numpy as np
        import pandas as pd  # noqa: F401
        import pyarrow  # noqa: F401
    except ImportError:
        for c in (
            "data_readable",
            "state_action_schema",
            "values_finite",
            "timestamps",
            "frame_consistency",
            "index_continuity",
        ):
            ctx.skip(c, "pandas/pyarrow not installed: parquet content NOT checked")
        rep.notes.append("pandas/pyarrow not installed: parquet content NOT checked (existence only)")
        return
    rep.parquet_checked = True
    widths = {
        k: (
            feats[k]["shape"][0]
            if isinstance(feats.get(k), dict)
            and isinstance(feats[k].get("shape"), list | tuple)
            and feats[k]["shape"]
            and isinstance(feats[k]["shape"][0], int)
            else None
        )
        for k in ("action", "observation.state")
    }
    for c in ("data_readable", "state_action_schema", "values_finite", "timestamps", "frame_consistency"):
        ctx.ran_(c)
    ranges: list[tuple[int, int, int]] = []  # (from, to, episode)
    for em in selected:
        ep, sub = em.episode_index, f"episode:{em.episode_index}"
        if em.data_relpath is None or not (root / em.data_relpath).is_file():
            ctx.error(
                "data_readable",
                QACode.MISSING_ARTIFACT,
                f"episode {ep}: declared data shard {em.data_relpath!r} does not exist",
                sub,
                relpath=em.data_relpath,
            )
            continue
        try:
            df = read_episode_rows(root, em)
        except Exception as exc:  # noqa: BLE001 - unreadable file is a QA finding, not a crash
            ctx.error(
                "data_readable",
                QACode.UNDECODABLE_FRAMES,
                f"episode {ep}: {em.data_relpath} cannot be read as parquet: {exc}",
                sub,
                relpath=em.data_relpath,
            )
            continue
        absent = [
            c for c in ("episode_index", "timestamp", "action", "observation.state") if c not in df.columns
        ]
        if absent:
            ctx.error(
                "state_action_schema",
                QACode.MISSING_FIELD,
                f"episode {ep}: {em.data_relpath} lacks column(s) {absent}",
                sub,
                relpath=em.data_relpath,
                columns=absent,
            )
            if "episode_index" in absent or "timestamp" in absent:
                continue
        n = len(df)
        if n == 0:
            ctx.error(
                "frame_consistency",
                QACode.LOW_COMPLETENESS,
                f"episode {ep}: no rows in {em.data_relpath}",
                sub,
            )
            continue
        if em.length is not None and n != em.length:
            ctx.error(
                "frame_consistency",
                QACode.LOW_COMPLETENESS,
                f"episode {ep}: {n} rows in {em.data_relpath} but metadata length is {em.length}",
                sub,
                rows=n,
                length=em.length,
            )
        for col in ("action", "observation.state"):
            if col not in df.columns:
                continue
            arr, problem = _finite_vec_col(df[col], widths[col])
            if arr is None:
                ctx.error(
                    "state_action_schema",
                    QACode.SCHEMA_MISMATCH,
                    f"episode {ep}: {col}: {problem}",
                    sub,
                    column=col,
                )
            elif not np.isfinite(arr).all():
                bad = np.argwhere(~np.isfinite(arr))
                ctx.error(
                    "values_finite",
                    QACode.NONFINITE_VALUE,
                    f"episode {ep}: {col} has {len(bad)} non-finite value(s); first at row {int(bad[0][0])}, "
                    f"dim {int(bad[0][1])}",
                    sub,
                    column=col,
                    first_row=int(bad[0][0]),
                    count=len(bad),
                )
        ts = pd_numeric(df["timestamp"])
        if ts is None:
            ctx.error(
                "timestamps", QACode.SCHEMA_MISMATCH, f"episode {ep}: timestamp column is not numeric", sub
            )
        elif not np.isfinite(ts).all():
            first = int(np.argwhere(~np.isfinite(ts))[0][0])
            ctx.error(
                "values_finite",
                QACode.NONFINITE_VALUE,
                f"episode {ep}: non-finite timestamp at row {first}",
                sub,
                column="timestamp",
                first_row=first,
            )
        else:
            bad_i = [i for i in range(1, len(ts)) if not ts[i] > ts[i - 1]]
            if bad_i:
                ctx.error(
                    "timestamps",
                    QACode.NONMONOTONIC_TIMESTAMPS,
                    f"episode {ep}: timestamps not strictly increasing at row offset {bad_i[0]}",
                    sub,
                    episode=ep,
                    first_index=bad_i[0],
                )
            elif rep.fps and n > 1:
                dt = np.diff(ts)
                if not np.allclose(dt, 1.0 / rep.fps, rtol=0.5):
                    ctx.error(
                        "timestamps",
                        QACode.NONMONOTONIC_TIMESTAMPS,
                        f"episode {ep}: timestamp spacing deviates >50% from 1/fps ({1.0 / rep.fps:.4f}s); "
                        f"min {dt.min():.4f}s max {dt.max():.4f}s",
                        sub,
                        episode=ep,
                    )
        if "frame_index" in df.columns:
            fi = pd_numeric(df["frame_index"])
            if fi is None or not (np.asarray(fi) == np.arange(n)).all():
                ctx.error(
                    "frame_consistency",
                    QACode.SCHEMA_MISMATCH,
                    f"episode {ep}: frame_index is not 0..{n - 1}",
                    sub,
                )
        else:
            ctx.error(
                "frame_consistency",
                QACode.MISSING_FIELD,
                f"episode {ep}: no frame_index column",
                sub,
                columns=["frame_index"],
            )
        if em.dataset_from_index is not None and em.dataset_to_index is not None:
            ranges.append((em.dataset_from_index, em.dataset_to_index, ep))
            if em.length is not None and em.dataset_to_index - em.dataset_from_index != em.length:
                ctx.error(
                    "index_continuity",
                    QACode.SCHEMA_MISMATCH,
                    f"episode {ep}: dataset_to_index-dataset_from_index != length",
                    sub,
                )
            if "index" in df.columns:
                ix = pd_numeric(df["index"])
                want = np.arange(em.dataset_from_index, em.dataset_from_index + n)
                if ix is None or len(ix) != n or not (np.asarray(ix) == want).all():
                    ctx.error(
                        "index_continuity",
                        QACode.SCHEMA_MISMATCH,
                        f"episode {ep}: global 'index' column does not match "
                        f"dataset_from_index={em.dataset_from_index}"
                        " (rows are not this episode's slice)",
                        sub,
                    )
    ctx.ran_("index_continuity")
    if not partial and ranges:
        ordered = sorted(ranges)
        if ordered[0][0] != 0:
            ctx.error(
                "index_continuity",
                QACode.LOW_COMPLETENESS,
                f"first episode starts at global index {ordered[0][0]}, not 0",
                "data/",
            )
        for (_f0, t0, e0), (f1, _t1, e1) in zip(ordered, ordered[1:], strict=False):
            if f1 != t0:
                ctx.error(
                    "index_continuity",
                    QACode.LOW_COMPLETENESS,
                    f"global index gap/overlap between episode {e0} (to {t0}) and episode {e1} (from {f1})",
                    "data/",
                )
    if not partial and rep.total_frames is not None:
        tot = rep.info.get("total_frames")
        if isinstance(tot, int) and tot != rep.total_frames:
            pass  # already reported by metadata check


def pd_numeric(series: Any) -> Any:
    """float ndarray from a numeric column, else None."""
    import numpy as np

    try:
        return np.asarray(series.to_numpy(dtype=float))
    except (ValueError, TypeError):
        return None


def _check_videos(
    root: Path,
    rep: DatasetReport,
    ctx: _Ctx,
    selected: list[EpisodeMeta],
    decode: bool,
    max_frames: int,
    tol: int,
) -> None:
    from robotevalops.qa.video_probe import VideoProbe, probe_video

    ctx.ran_("video_present")
    cache: dict[str, VideoProbe] = {}
    if not decode:
        ctx.skip("video_decodable", "decode_videos=False")
        ctx.skip("video_alignment", "decode_videos=False")
    else:
        ctx.ran_("video_decodable")
        ctx.ran_("video_alignment")
    fps = rep.fps
    for em in selected:
        sub = f"episode:{em.episode_index}"
        for cam in rep.cameras:
            ref: VideoRef | None = em.videos.get(cam)
            if ref is None or ref.relpath is None:
                ctx.error(
                    "video_present",
                    QACode.MISSING_VIDEO,
                    f"episode {em.episode_index}: no video file resolvable for camera {cam!r} in metadata",
                    sub,
                    camera=cam,
                )
                continue
            path = root / ref.relpath
            if not path.is_file():
                ctx.error(
                    "video_present",
                    QACode.MISSING_VIDEO,
                    f"episode {em.episode_index}: camera {cam!r} video {ref.relpath} is missing",
                    sub,
                    camera=cam,
                    relpath=ref.relpath,
                )
                continue
            if not decode:
                continue
            probe = cache.get(ref.relpath)
            if probe is None:
                probe = cache[ref.relpath] = probe_video(path, max_frames=max_frames)
                if probe.error is None and not probe.truncated:
                    rep.videos_decoded += 1
            if probe.error is not None or probe.frames == 0:
                ctx.error(
                    "video_decodable",
                    QACode.UNDECODABLE_FRAMES,
                    f"episode {em.episode_index}: camera {cam!r} {ref.relpath} cannot be decoded "
                    f"({probe.error or 'zero frames'})",
                    sub,
                    camera=cam,
                    relpath=ref.relpath,
                )
                continue
            if probe.truncated:
                ctx.skip(
                    "video_alignment", f"{ref.relpath}: more than {max_frames} frames; decode budget exceeded"
                )
                continue
            if ref.from_timestamp is None or ref.to_timestamp is None or em.length is None or not fps:
                ctx.error(
                    "video_alignment",
                    QACode.MISSING_FIELD,
                    f"episode {em.episode_index}: camera {cam!r} has no usable from/to timestamps "
                    "or length/fps",
                    sub,
                    camera=cam,
                )
                continue
            half = 0.5 / fps
            in_win = [
                t for t in probe.times if ref.from_timestamp - half <= t < ref.to_timestamp - half + 1e-9
            ]
            if abs(len(in_win) - em.length) > tol:
                ctx.error(
                    "video_alignment",
                    QACode.TRUNCATED_VIDEO,
                    f"episode {em.episode_index}: camera {cam!r} has {len(in_win)} decoded frames in window "
                    f"[{ref.from_timestamp:.3f}, {ref.to_timestamp:.3f}) of {ref.relpath} but the "
                    "episode has "
                    f"{em.length} state/action rows (tolerance {tol})",
                    sub,
                    camera=cam,
                    frames=len(in_win),
                    rows=em.length,
                    window=[ref.from_timestamp, ref.to_timestamp],
                )
            elif in_win and abs(in_win[0] - ref.from_timestamp) > 2 * half:
                ctx.error(
                    "video_alignment",
                    QACode.TRUNCATED_VIDEO,
                    f"episode {em.episode_index}: camera {cam!r} first frame in window is at "
                    f"{in_win[0]:.3f}s, "
                    f"expected ~{ref.from_timestamp:.3f}s",
                    sub,
                    camera=cam,
                )
            if ref.to_timestamp > probe.duration + 2 * half:
                ctx.error(
                    "video_alignment",
                    QACode.TRUNCATED_VIDEO,
                    f"episode {em.episode_index}: camera {cam!r} window ends at {ref.to_timestamp:.3f}s but "
                    f"{ref.relpath} only decodes {probe.duration:.3f}s",
                    sub,
                    camera=cam,
                )
