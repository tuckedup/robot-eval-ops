"""Per-trial QA: combines checks into a QAReport and applies the demonstration acceptance rubric
(docs/templates/demonstration-acceptance-checklist.md; thresholds below must match it)."""

from __future__ import annotations

from pathlib import Path

from robotevalops.qa import checks
from robotevalops.recording.manifest import entry_completeness, entry_flags
from robotevalops.schemas import (
    ArtifactRole,
    Intervention,
    QACode,
    QAFlag,
    QAReport,
    Severity,
    TaskOutcome,
    TrialManifestEntry,
    TrialState,
)

ACCEPT_MIN_COMPLETENESS = 0.98
ACCEPT_MIN_DURATION_S = 1.0


def _first(entry: TrialManifestEntry, role: ArtifactRole) -> str | None:
    return next((a.relpath for a in entry.artifacts if a.role == role), None)


def qa_trial(
    run_dir: str | Path,
    entry: TrialManifestEntry,
    *,
    require_video: bool = True,
    expected_frames: int | None = None,
    min_duration_s: float = ACCEPT_MIN_DURATION_S,
    min_completeness: float = ACCEPT_MIN_COMPLETENESS,
) -> QAReport:
    """Run all checks for one trial. Any ERROR flag => report.quality == FAIL.

    expected_frames: frames the recorder wrote/expected (RecordingSummary.frames_expected); when None the
    number of trace rows is used, which assumes one video frame per trace row.
    """
    root = Path(run_dir)
    tid = entry.trial_id
    flags: list[QAFlag] = list(entry_flags(entry))
    trace_rel = _first(entry, ArtifactRole.TRACE)
    video_rel = _first(entry, ArtifactRole.VIDEO)
    n_rows: int | None = None
    trace_duration: float | None = None

    # trace
    if trace_rel is None or not (root / trace_rel).is_file():
        flags.append(
            QAFlag(
                code=QACode.MISSING_ARTIFACT,
                severity=Severity.ERROR,
                subject=tid,
                message=f"trace for trial {tid} is missing ({trace_rel or 'not listed in manifest'}); "
                "re-record or restore it - the trial has no state/action evidence",
                evidence={"relpath": trace_rel, "role": "trace"},
            )
        )
    else:
        tr, tflags = checks.check_trace(root / trace_rel, tid, trace_rel)
        flags.extend(tflags)
        n_rows = len(tr.rows)
        ts = [r["t"] for r in tr.rows if isinstance(r.get("t"), int | float)]
        if len(ts) >= 2:
            trace_duration = float(ts[-1]) - float(ts[0])

    # video
    if video_rel is not None or require_video:
        flags.extend(
            checks.check_video(
                root, video_rel, expected_frames if expected_frames is not None else n_rows, tid
            )
        )

    # other artifacts (video/trace handled above) + hashes
    others = [a for a in entry.artifacts if a.role not in (ArtifactRole.VIDEO, ArtifactRole.TRACE)]
    flags.extend(checks.check_artifacts_present(root, others, tid))
    flags.extend(checks.check_hashes(root, entry.artifacts, tid))
    flags.extend(checks.check_outcome_label(entry.task_outcome.value, tid))

    completeness = entry_completeness(entry)
    flags.extend(checks.check_low_completeness(completeness, min_completeness, tid))

    # --- acceptance rubric
    reasons: list[str] = []
    errors = [f for f in flags if f.severity == Severity.ERROR]
    if errors:
        reasons.append("QA errors present: " + ", ".join(sorted({f.code.value for f in errors})))
    if completeness < min_completeness:
        reasons.append(f"required-metadata completeness {completeness:.3f} < {min_completeness}")
    duration = entry.duration_s if entry.duration_s is not None else trace_duration
    if duration is None:
        reasons.append("duration unknown (no duration_s and no usable trace timestamps)")
    elif duration < min_duration_s:
        reasons.append(f"duration {duration:.3f}s < minimum {min_duration_s}s")
    if entry.task_outcome == TaskOutcome.UNSCORED:
        reasons.append("no outcome label (task_outcome is unscored)")
    if entry.intervention == Intervention.UNKNOWN:
        reasons.append("operator intervention not noted (intervention is unknown)")
    if entry.state != TrialState.COMPLETED:
        reasons.append(f"trial state is {entry.state.value}, not completed")

    return QAReport(subject=tid, flags=flags, accepted=not reasons, rejection_reasons=reasons)
