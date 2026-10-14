"""Hand-built TrialRecords with KNOWN counts (no service, no randomness)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count

from robotevalops.schemas import (
    ControllerType,
    Intervention,
    Provenance,
    RecordingQuality,
    TaskOutcome,
    TerminationReason,
    TrialRecord,
    TrialState,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
_ids = count(1)

C, F, A = TrialState.COMPLETED, TrialState.FAILED, TrialState.ABORTED
S, FL, UN = TaskOutcome.SUCCESS, TaskOutcome.FAILURE, TaskOutcome.UNSCORED
OK, TO = TerminationReason.SUCCESS_CRITERION_MET, TerminationReason.TIMEOUT
NONE, ASS = Intervention.NONE, Intervention.ASSISTED
PASS, FLAG, FAILQ = RecordingQuality.PASS, RecordingQuality.FLAGGED, RecordingQuality.FAIL
UNCHECKED = RecordingQuality.UNCHECKED


def make_trial(
    *,
    controller_id: str = "A",
    condition: str = "c0",
    trial_index: int | None = None,
    state: TrialState = TrialState.PLANNED,
    outcome: TaskOutcome = TaskOutcome.UNSCORED,
    reason: TerminationReason = TerminationReason.NOT_RUN,
    intervention: Intervention = Intervention.UNKNOWN,
    quality: RecordingQuality = RecordingQuality.UNCHECKED,
    duration: float | None = None,
    attempted: bool | None = None,
    provenance: Provenance = Provenance.SIMULATION,
    controller_type: ControllerType = ControllerType.SCRIPTED,
    session_id: str = "s1",
    seed: int | None = None,
    controller_config_hash: str = "h" * 8,
    **extra,
) -> TrialRecord:
    n = next(_ids)
    ti = n if trial_index is None else trial_index
    if attempted is None:
        attempted = state not in (TrialState.PLANNED, TrialState.PREFLIGHT, TrialState.READY)
    return TrialRecord(
        trial_id=f"t{n:04d}",
        session_id=session_id,
        schedule_position=n,
        controller_id=controller_id,
        controller_type=controller_type,
        controller_version="1",
        controller_config_hash=controller_config_hash,
        condition_name=condition,
        condition_kind="nominal",
        trial_index=ti,
        seed=1000 + ti if seed is None else seed,
        provenance=provenance,
        backend="mock" if provenance == Provenance.MOCK else "pybullet_panda",
        state=state,
        task_outcome=outcome,
        termination_reason=reason,
        intervention=intervention,
        recording_quality=quality,
        planned_at=T0,
        started_at=T0 + timedelta(seconds=1) if attempted else None,
        duration_s=duration,
        **extra,
    )


def known_scenario(provenance: Provenance = Provenance.SIMULATION, **kw) -> list[TrialRecord]:
    """20 planned: 15 attempted. completed 10 (4 autonomous, 1 quality-fail success, 2 assisted successes,
    2 failures, 1 unscored), failed 2 (infra), aborted 3, never attempted 5."""

    def mk(**k) -> TrialRecord:
        return make_trial(provenance=provenance, **kw, **k)

    ts: list[TrialRecord] = []
    for d in (10.0, 12.0, 14.0, 16.0):
        ts.append(mk(state=C, outcome=S, reason=OK, intervention=NONE, quality=PASS, duration=d))
    ts.append(mk(state=C, outcome=S, reason=OK, intervention=NONE, quality=FAILQ, duration=18.0))
    for _ in range(2):
        ts.append(mk(state=C, outcome=S, reason=OK, intervention=ASS, quality=FLAG, duration=3.0))
    for _ in range(2):
        ts.append(mk(state=C, outcome=FL, reason=TO, intervention=NONE, quality=PASS, duration=30.0))
    ts.append(mk(state=C, outcome=UN, reason=OK, duration=5.0))
    ts.append(mk(state=F, reason=TerminationReason.INFRA_FAILURE))
    ts.append(mk(state=F, reason=TerminationReason.RECORDING_FAILURE))
    ts.append(mk(state=A, reason=TerminationReason.OPERATOR_ABORT, duration=0.2))
    ts.append(mk(state=A, reason=TerminationReason.SOFTWARE_STOP_REQUEST))
    ts.append(mk(state=A, reason=TerminationReason.INTERRUPTED_RUNNER))
    for _ in range(5):
        ts.append(mk())
    assert len(ts) == 20
    return ts
