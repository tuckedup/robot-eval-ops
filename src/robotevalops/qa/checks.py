"""Individual QA checks. Each returns a list of QAFlag with actionable messages.

Checks only observe; they never repair, interpolate or invent timestamps/states.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from robotevalops.schemas import ArtifactRef, ArtifactRole, QACode, QAFlag, Severity
from robotevalops.util import SCHEMA_VERSION, sha256_file

MAX_EXAMPLES = 5


def _flag(code: QACode, sev: Severity, msg: str, subject: str = "", **evidence: Any) -> QAFlag:
    return QAFlag(code=code, severity=sev, message=msg, subject=subject, evidence=evidence)


# --------------------------------------------------------------------------- video


@dataclass
class VideoProbe:
    opened: bool = False
    header_frames: int = 0
    decoded_frames: int = 0
    bad_frames: int = 0
    has_moov: bool = False
    size_bytes: int = 0


def probe_video(path: Path) -> VideoProbe:
    """Open with OpenCV and actually decode every frame (header counts are not trusted)."""
    import cv2

    p = VideoProbe(size_bytes=path.stat().st_size)
    with open(path, "rb") as f:
        p.has_moov = b"moov" in f.read()
    cap = cv2.VideoCapture(str(path))
    try:
        p.opened = bool(cap.isOpened())
        if not p.opened:
            return p
        p.header_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame is None or frame.size == 0:
                p.bad_frames += 1
            else:
                p.decoded_frames += 1
    finally:
        cap.release()
    return p


def check_video(
    run_dir: Path, relpath: str | None, expected_frames: int | None = None, subject: str = ""
) -> list[QAFlag]:
    """Missing / truncated / undecodable video. `expected_frames` (e.g. trace row count) is optional;
    when given, decoded < expected is flagged as truncation."""
    subject = subject or (relpath or "video")
    if not relpath or not (run_dir / relpath).is_file():
        return [
            _flag(
                QACode.MISSING_VIDEO,
                Severity.ERROR,
                f"video {relpath or '(none listed)'} is missing for {subject}; re-record the trial "
                "or locate the file (do not mark the trial successful without video evidence)",
                subject,
                relpath=relpath,
            )
        ]
    path = run_dir / relpath
    pr = probe_video(path)
    ev: dict[str, Any] = {
        "relpath": relpath,
        **{
            k: getattr(pr, k)
            for k in ("header_frames", "decoded_frames", "bad_frames", "has_moov", "size_bytes")
        },
    }
    if pr.size_bytes == 0:
        return [
            _flag(
                QACode.TRUNCATED_VIDEO,
                Severity.ERROR,
                f"{relpath} is a zero-byte file; the recording was cut off - re-record",
                subject,
                **ev,
            )
        ]
    if not pr.opened:
        if not pr.has_moov:
            return [
                _flag(
                    QACode.TRUNCATED_VIDEO,
                    Severity.ERROR,
                    f"{relpath} cannot be opened and has no container index (moov atom): the file "
                    "looks truncated (interrupted write or partial transfer); re-record or re-download",
                    subject,
                    **ev,
                )
            ]
        return [
            _flag(
                QACode.UNDECODABLE_FRAMES,
                Severity.ERROR,
                f"{relpath} has a container index but OpenCV cannot open it; the codec may be "
                "unsupported or the file corrupt - re-encode or re-record",
                subject,
                **ev,
            )
        ]
    flags: list[QAFlag] = []
    if pr.decoded_frames == 0 or pr.bad_frames:
        flags.append(
            _flag(
                QACode.UNDECODABLE_FRAMES,
                Severity.ERROR,
                f"{relpath}: decoded {pr.decoded_frames} frames, {pr.bad_frames} empty/undecodable; "
                "the file is corrupt - re-record",
                subject,
                **ev,
            )
        )
    if pr.header_frames and pr.decoded_frames < pr.header_frames:
        flags.append(
            _flag(
                QACode.TRUNCATED_VIDEO,
                Severity.ERROR,
                f"{relpath}: header/container reports {pr.header_frames} frames but only "
                f"{pr.decoded_frames} decode; the file is truncated - re-record or re-download",
                subject,
                **ev,
            )
        )
    elif expected_frames is not None and pr.decoded_frames < expected_frames:
        flags.append(
            _flag(
                QACode.TRUNCATED_VIDEO,
                Severity.ERROR,
                f"{relpath}: {pr.decoded_frames} frames decoded but {expected_frames} expected "
                "from the trace; frames were dropped or the file is truncated",
                subject,
                expected_frames=expected_frames,
                **ev,
            )
        )
    return flags


# --------------------------------------------------------------------------- trace


@dataclass
class ParsedTrace:
    header: dict[str, Any] | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)
    row_lines: list[int] = field(default_factory=list)  # 1-based file line of each row
    nonfinite_tokens: list[tuple[int, str]] = field(default_factory=list)  # (line, token)
    parse_errors: list[tuple[int, str]] = field(default_factory=list)


def load_trace(path: Path) -> ParsedTrace:
    """Parse trace.jsonl, capturing NaN/Infinity literals via parse_constant (Python's json emits them)."""
    out = ParsedTrace()
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            if not line.strip():
                continue
            captured: list[str] = []

            def _const(tok: str, _c: list[str] = captured) -> float:
                _c.append(tok)
                return float(tok.replace("Infinity", "inf").replace("NaN", "nan"))

            try:
                obj = json.loads(line, parse_constant=_const)
            except json.JSONDecodeError as exc:
                out.parse_errors.append((lineno, str(exc)))
                continue
            out.nonfinite_tokens.extend((lineno, tok) for tok in captured)
            if not isinstance(obj, dict):
                out.parse_errors.append((lineno, "line is not a JSON object"))
                continue
            if out.header is None and obj.get("kind") == "header":
                out.header = obj
            elif out.header is None and not out.rows and lineno == 1:
                out.header = obj  # first line is the header slot even if malformed
            else:
                out.rows.append(obj)
                out.row_lines.append(lineno)
    return out


def check_trace_schema(tr: ParsedTrace, subject: str, relpath: str = "trace.jsonl") -> list[QAFlag]:
    """Header kind/schema_version, row field presence and vector lengths vs header names."""
    flags: list[QAFlag] = []
    ev = {"relpath": relpath}
    for lineno, msg in tr.parse_errors[:MAX_EXAMPLES]:
        flags.append(
            _flag(
                QACode.SCHEMA_MISMATCH,
                Severity.ERROR,
                f"{relpath} line {lineno} is not valid JSON ({msg}); the trace is corrupt - "
                "re-record or restore from backup",
                subject,
                line=lineno,
                **ev,
            )
        )
    h = tr.header
    if h is None:
        flags.append(
            _flag(
                QACode.SCHEMA_MISMATCH,
                Severity.ERROR,
                f"{relpath} has no header line; expected a TraceHeader object on line 1",
                subject,
                **ev,
            )
        )
        return flags
    if h.get("kind") != "header":
        flags.append(
            _flag(
                QACode.SCHEMA_MISMATCH,
                Severity.ERROR,
                f"{relpath} line 1 has kind={h.get('kind')!r}, expected 'header'",
                subject,
                found=h.get("kind"),
                **ev,
            )
        )
    if h.get("schema_version") != SCHEMA_VERSION:
        flags.append(
            _flag(
                QACode.SCHEMA_MISMATCH,
                Severity.ERROR,
                f"{relpath} schema_version {h.get('schema_version')!r} != supported "
                f"{SCHEMA_VERSION!r}; migrate or re-record with a matching version",
                subject,
                found=h.get("schema_version"),
                expected=SCHEMA_VERSION,
                **ev,
            )
        )
    names: dict[str, list[Any]] = {}
    for k in ("state_names", "action_names"):
        v = h.get(k)
        if not isinstance(v, list) or not v:
            flags.append(
                _flag(
                    QACode.MISSING_FIELD,
                    Severity.ERROR,
                    f"{relpath} header lacks a non-empty {k!r} list; cannot validate rows",
                    subject,
                    field=k,
                    **ev,
                )
            )
        else:
            names[k] = v
    for k in ("fps", "provenance"):
        if h.get(k) in (None, ""):
            flags.append(
                _flag(
                    QACode.MISSING_FIELD,
                    Severity.ERROR,
                    f"{relpath} header lacks {k!r}",
                    subject,
                    field=k,
                    **ev,
                )
            )
    bad: list[dict[str, Any]] = []
    for idx, (row, line) in enumerate(zip(tr.rows, tr.row_lines, strict=True)):
        problems = []
        for k in ("i", "t", "state", "action"):
            if k not in row:
                problems.append(f"missing field {k!r}")
        for k, nk in (("state", "state_names"), ("action", "action_names")):
            v = row.get(k)
            if k in row and nk in names and (not isinstance(v, list) or len(v) != len(names[nk])):
                got = len(v) if isinstance(v, list) else type(v).__name__
                problems.append(f"{k} has length {got}, header declares {len(names[nk])}")
        if problems:
            bad.append({"row_index": idx, "line": line, "problems": problems})
    if bad:
        first = bad[0]
        flags.append(
            _flag(
                QACode.MISSING_FIELD,
                Severity.ERROR,
                f"{relpath}: {len(bad)} row(s) have missing or wrong-length fields; first at row "
                f"{first['row_index']} (line {first['line']}): {'; '.join(first['problems'])}. "
                "Fix the recorder or re-record; rows are not repaired automatically",
                subject,
                count=len(bad),
                examples=bad[:MAX_EXAMPLES],
                **ev,
            )
        )
    return flags


def check_timestamps(tr: ParsedTrace, subject: str, relpath: str = "trace.jsonl") -> list[QAFlag]:
    """t must be non-decreasing (equal timestamps allowed). Reports the first offending row index."""
    prev: float | None = None
    for idx, (row, line) in enumerate(zip(tr.rows, tr.row_lines, strict=True)):
        t = row.get("t")
        if not isinstance(t, int | float) or isinstance(t, bool) or not math.isfinite(t):
            continue  # missing/non-finite t is reported by schema/nonfinite checks
        if prev is not None and t < prev:
            return [
                _flag(
                    QACode.NONMONOTONIC_TIMESTAMPS,
                    Severity.ERROR,
                    f"{relpath}: timestamp goes backwards at row {idx} (line {line}): t={t} after "
                    f"{prev}. The recorder clock or file order is wrong; re-record. Timestamps are "
                    "never re-sorted or synthesised",
                    subject,
                    relpath=relpath,
                    first_index=idx,
                    line=line,
                    t=t,
                    previous_t=prev,
                )
            ]
        prev = float(t)
    return []


def check_nonfinite(tr: ParsedTrace, subject: str, relpath: str = "trace.jsonl") -> list[QAFlag]:
    """NaN/Infinity literals (captured at parse time) or overflowed floats in state/action/t."""
    hits: list[dict[str, Any]] = []
    for idx, (row, line) in enumerate(zip(tr.rows, tr.row_lines, strict=True)):
        for k in ("t", "state", "action"):
            v = row.get(k)
            vals = v if isinstance(v, list) else [v]
            for j, x in enumerate(vals):
                if isinstance(x, float) and not math.isfinite(x):
                    hits.append({"row_index": idx, "line": line, "field": k, "element": j, "value": repr(x)})
    if not hits and not tr.nonfinite_tokens:
        return []
    first = hits[0] if hits else {"line": tr.nonfinite_tokens[0][0]}
    return [
        _flag(
            QACode.NONFINITE_VALUE,
            Severity.ERROR,
            f"{relpath}: {max(len(hits), len(tr.nonfinite_tokens))} non-finite (NaN/Inf) value(s); first at "
            f"line {first['line']}"
            + (f", row {first['row_index']} field {first['field']}[{first['element']}]" if hits else "")
            + ". Check the sensor/controller for numerical failure and re-record; do not use this trial "
            "for scoring or training",
            subject,
            relpath=relpath,
            count=len(hits),
            tokens=[t for _, t in tr.nonfinite_tokens[:MAX_EXAMPLES]],
            examples=hits[:MAX_EXAMPLES],
        )
    ]


def check_trace(path: Path, subject: str, relpath: str = "trace.jsonl") -> tuple[ParsedTrace, list[QAFlag]]:
    tr = load_trace(path)
    flags = [
        *check_trace_schema(tr, subject, relpath),
        *check_timestamps(tr, subject, relpath),
        *check_nonfinite(tr, subject, relpath),
    ]
    return tr, flags


# --------------------------------------------------------------------------- artifacts / ids


def check_artifacts_present(
    run_dir: Path, artifacts: Iterable[ArtifactRef], subject: str = ""
) -> list[QAFlag]:
    flags: list[QAFlag] = []
    for a in artifacts:
        if (run_dir / a.relpath).is_file():
            continue
        if a.role == ArtifactRole.MODEL:
            flags.append(
                _flag(
                    QACode.MISSING_MODEL_ARTIFACT,
                    Severity.ERROR,
                    f"model artifact {a.relpath} referenced by {subject or 'trial'} does not exist; "
                    "restore the checkpoint/config or do not claim this controller ran",
                    subject,
                    relpath=a.relpath,
                    sha256=a.sha256,
                )
            )
        elif a.role == ArtifactRole.VIDEO:
            flags.extend(check_video(run_dir, a.relpath, subject=subject))
        else:
            flags.append(
                _flag(
                    QACode.MISSING_ARTIFACT,
                    Severity.ERROR,
                    f"artifact {a.relpath} ({a.role.value}) listed for {subject or 'trial'} is missing "
                    "on disk; restore it from the store or re-record",
                    subject,
                    relpath=a.relpath,
                    role=a.role.value,
                )
            )
    return flags


def check_hashes(run_dir: Path, artifacts: Iterable[ArtifactRef], subject: str = "") -> list[QAFlag]:
    """Recompute SHA-256 of files that exist and compare to the recorded hash."""
    flags: list[QAFlag] = []
    for a in artifacts:
        p = run_dir / a.relpath
        if not p.is_file():
            continue
        if not a.sha256:
            flags.append(
                _flag(
                    QACode.MISSING_FIELD,
                    Severity.WARNING,
                    f"artifact {a.relpath} has no recorded sha256; integrity cannot be checked - "
                    "record the hash at write time",
                    subject,
                    relpath=a.relpath,
                    field="sha256",
                )
            )
            continue
        actual = sha256_file(p)
        if actual != a.sha256:
            flags.append(
                _flag(
                    QACode.HASH_MISMATCH,
                    Severity.ERROR,
                    f"{a.relpath}: recomputed sha256 {actual[:12]}... != recorded {a.sha256[:12]}...; "
                    "the file changed after recording (corruption or tampering). Keep the file as "
                    "evidence, restore from a verified copy",
                    subject,
                    relpath=a.relpath,
                    expected=a.sha256,
                    actual=actual,
                )
            )
    return flags


def check_duplicate_ids(ids: Iterable[str], kind: str = "trial_id", subject: str = "") -> list[QAFlag]:
    counts: dict[str, int] = {}
    for i in ids:
        counts[i] = counts.get(i, 0) + 1
    return [
        _flag(
            QACode.DUPLICATE_ID,
            Severity.ERROR,
            f"{kind} {i!r} occurs {n} times; identifiers must be unique - re-issue ids, never merge "
            "or delete records",
            subject or i,
            id=i,
            count=n,
        )
        for i, n in counts.items()
        if n > 1
    ]


def check_outcome_label(task_outcome: str, subject: str = "") -> list[QAFlag]:
    if task_outcome == "unscored":
        return [
            _flag(
                QACode.MISSING_OUTCOME,
                Severity.WARNING,
                f"{subject or 'trial'} has no outcome label (unscored); label it from physics evidence "
                "or operator video review before using it",
                subject,
            )
        ]
    return []


def check_low_completeness(value: float, threshold: float, subject: str = "") -> list[QAFlag]:
    if value < threshold:
        return [
            _flag(
                QACode.LOW_COMPLETENESS,
                Severity.WARNING,
                f"{subject or 'recording'} completeness {value:.3f} < {threshold:.2f}; see the missing "
                "fields/frames in the other flags and re-record or complete the metadata",
                subject,
                completeness=value,
                threshold=threshold,
            )
        ]
    return []
