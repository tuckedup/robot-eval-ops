# ruff: noqa: E501, B023
"""V2: lifecycle + accounting attacks through the public EvalService, and an independent hand computation of
the contracts.md section 5 denominators on a tiny dataset built only through the service."""

from __future__ import annotations

import math
import threading
from pathlib import Path

import pytest

from robotevalops.core.service import EvalService
from robotevalops.errors import (
    DeviceBusyError,
    InvalidTransitionError,
    ScoreProtectionError,
)
from robotevalops.metrics.compute import compute_metrics
from robotevalops.schemas import (
    ArtifactRef,
    ArtifactRole,
    ArtifactStatus,
    ConditionSpec,
    ControllerSpec,
    ControllerType,
    EvalConfig,
    Intervention,
    Provenance,
    RecordingQuality,
    ScoreSource,
    TaskOutcome,
    TerminationReason,
    TrialState,
    is_autonomous_success,
)


def _cfg(n_ctrl: int = 1, n_cond: int = 1, trials: int = 1, types=None) -> EvalConfig:
    types = types or [ControllerType.SCRIPTED] * n_ctrl
    return EvalConfig(
        name="v",
        provenance=Provenance.MOCK,
        backend="mock",
        controllers=[
            ControllerSpec(controller_id=f"c{i}", type=types[i], version="1", config={"i": i})
            for i in range(n_ctrl)
        ],
        conditions=[ConditionSpec(name=f"k{i}", kind="nominal") for i in range(n_cond)],
        trials_per_condition=trials,
        base_seed=3,
    )


def _session(tmp_path: Path, cfg: EvalConfig):
    svc = EvalService(tmp_path / "home")
    s = svc.create_session("v", Provenance.MOCK, "mock", eval_config=cfg)
    return svc, s, svc.plan_trials(s.session_id, cfg)


def _start(svc: EvalService, tid: str) -> None:
    for st in (TrialState.PREFLIGHT, TrialState.READY, TrialState.RUNNING):
        svc.transition_trial(tid, st)


def _finish(svc, tid, reason=TerminationReason.SUCCESS_CRITERION_MET, outcome=None, interv=None, dur=1.0):
    return svc.record_trial_result(
        tid,
        termination_reason=reason,
        duration_s=dur,
        task_outcome=outcome,
        score_source=ScoreSource.MOCK_FIXTURE if outcome else None,
        intervention=interv,
    )


# ---------------------------------------------------------------- illegal transitions / terminal states
@pytest.mark.parametrize(
    ("path", "bad"),
    [
        ([], TrialState.RUNNING),
        ([], TrialState.COMPLETED),
        ([TrialState.PREFLIGHT], TrialState.RUNNING),
        ([TrialState.PREFLIGHT, TrialState.READY], TrialState.COMPLETED),
        ([TrialState.PREFLIGHT, TrialState.READY, TrialState.RUNNING], TrialState.PLANNED),
        ([TrialState.PREFLIGHT, TrialState.READY, TrialState.RUNNING], TrialState.READY),
    ],
)
def test_illegal_transitions_are_rejected(tmp_path: Path, path, bad) -> None:
    svc, _, trials = _session(tmp_path, _cfg())
    tid = trials[0].trial_id
    for st in path:
        svc.transition_trial(tid, st)
    with pytest.raises(InvalidTransitionError):
        svc.transition_trial(tid, bad)


@pytest.mark.parametrize(
    "terminal_reason",
    [
        TerminationReason.SUCCESS_CRITERION_MET,
        TerminationReason.INFRA_FAILURE,
        TerminationReason.OPERATOR_ABORT,
    ],
)
def test_terminal_states_reject_every_transition_and_result_rewrite(tmp_path: Path, terminal_reason) -> None:
    svc, _, trials = _session(tmp_path, _cfg())
    tid = trials[0].trial_id
    _start(svc, tid)
    _finish(svc, tid, terminal_reason)
    for st in TrialState:
        with pytest.raises(InvalidTransitionError):
            svc.transition_trial(tid, st)
    with pytest.raises(InvalidTransitionError):
        _finish(svc, tid, TerminationReason.SUCCESS_CRITERION_MET, TaskOutcome.SUCCESS, Intervention.NONE)


def test_wrong_termination_reason_for_state_rejected(tmp_path: Path) -> None:
    svc, _, trials = _session(tmp_path, _cfg())
    tid = trials[0].trial_id
    _start(svc, tid)
    with pytest.raises(InvalidTransitionError):
        svc.transition_trial(tid, TrialState.COMPLETED, termination_reason=TerminationReason.INFRA_FAILURE)
    with pytest.raises(InvalidTransitionError):  # FAILED + success reason would smuggle a success reason in
        svc.transition_trial(
            tid, TrialState.FAILED, termination_reason=TerminationReason.SUCCESS_CRITERION_MET
        )


def test_failed_trial_cannot_carry_outcome(tmp_path: Path) -> None:
    svc, _, trials = _session(tmp_path, _cfg())
    tid = trials[0].trial_id
    _start(svc, tid)
    with pytest.raises(ValueError):
        _finish(svc, tid, TerminationReason.INFRA_FAILURE, TaskOutcome.SUCCESS)
    assert svc.get_trial(tid).state == TrialState.RUNNING  # nothing half-applied


# ---------------------------------------------------------------- scoring protection
@pytest.mark.parametrize(
    "final",
    [
        TerminationReason.INFRA_FAILURE,
        TerminationReason.RECORDING_FAILURE,
        TerminationReason.OPERATOR_ABORT,
        TerminationReason.INTERRUPTED_RUNNER,
    ],
)
def test_cannot_score_non_completed_trials(tmp_path: Path, final) -> None:
    svc, _, trials = _session(tmp_path, _cfg(1, 1, 3))
    planned, running, done = trials[0].trial_id, trials[1].trial_id, trials[2].trial_id
    _start(svc, running)
    _start(svc, done)
    _finish(svc, done, final)
    for tid in (planned, running, done):
        with pytest.raises(InvalidTransitionError):
            svc.score_trial(
                tid,
                TaskOutcome.SUCCESS,
                source=ScoreSource.OPERATOR_VIDEO,
                scorer="a",
                intervention=Intervention.NONE,
            )
        with pytest.raises(InvalidTransitionError):
            svc.edit_score(
                tid,
                TaskOutcome.SUCCESS,
                source=ScoreSource.OPERATOR_VIDEO,
                editor="a",
                reason="x",
                intervention=Intervention.NONE,
            )
        assert svc.get_trial(tid).task_outcome == TaskOutcome.UNSCORED


def _completed_unscored(svc, tid):
    _start(svc, tid)
    return _finish(svc, tid)


def test_double_score_and_edit_audit(tmp_path: Path) -> None:
    svc, _, trials = _session(tmp_path, _cfg())
    tid = trials[0].trial_id
    _completed_unscored(svc, tid)
    svc.score_trial(
        tid,
        TaskOutcome.FAILURE,
        source=ScoreSource.OPERATOR_VIDEO,
        scorer="a",
        intervention=Intervention.NONE,
    )
    with pytest.raises(ScoreProtectionError):
        svc.score_trial(
            tid,
            TaskOutcome.SUCCESS,
            source=ScoreSource.OPERATOR_VIDEO,
            scorer="b",
            intervention=Intervention.NONE,
        )
    assert svc.get_trial(tid).task_outcome == TaskOutcome.FAILURE
    for bad_reason in ("", "   ", "\n\t"):
        with pytest.raises(ValueError):
            svc.edit_score(
                tid,
                TaskOutcome.SUCCESS,
                source=ScoreSource.OPERATOR_VIDEO,
                editor="b",
                reason=bad_reason,
                intervention=Intervention.NONE,
            )
    assert svc.get_trial(tid).task_outcome == TaskOutcome.FAILURE
    assert svc.list_score_edits(tid) == []
    e = svc.edit_score(
        tid,
        TaskOutcome.SUCCESS,
        source=ScoreSource.OPERATOR_VIDEO,
        editor="b",
        reason="video shows block inside",
        intervention=Intervention.NONE,
    )
    assert (e.before_outcome, e.after_outcome) == (TaskOutcome.FAILURE, TaskOutcome.SUCCESS)
    assert len(svc.list_score_edits(tid)) == 1


def test_concurrent_score_exactly_one_wins(tmp_path: Path) -> None:
    svc, _, trials = _session(tmp_path, _cfg())
    tid = trials[0].trial_id
    _completed_unscored(svc, tid)
    home = svc.home
    barrier = threading.Barrier(8)
    results: list[str] = []

    def worker(i: int) -> None:
        s = EvalService(home)
        barrier.wait()
        try:
            s.score_trial(
                tid,
                TaskOutcome.SUCCESS if i % 2 else TaskOutcome.FAILURE,
                source=ScoreSource.OPERATOR_VIDEO,
                scorer=f"s{i}",
                intervention=Intervention.NONE,
            )
            results.append("ok")
        except ScoreProtectionError:
            results.append("protected")
        except Exception as e:  # noqa: BLE001
            results.append(f"other:{type(e).__name__}:{e}")

    ths = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    assert results.count("ok") == 1, results
    assert results.count("protected") == 7, results


# ---------------------------------------------------------------- autonomy / provenance accounting
def test_intervention_and_controller_type_never_yield_autonomous_success(tmp_path: Path) -> None:
    cfg = _cfg(2, 1, 3, [ControllerType.SCRIPTED, ControllerType.TELEOPERATED])
    svc, _, trials = _session(tmp_path, cfg)
    by = {(t.controller_id, t.trial_index): t.trial_id for t in trials}
    # scripted: none -> autonomous; assisted / unknown -> not
    for idx, interv in enumerate((Intervention.NONE, Intervention.ASSISTED, Intervention.UNKNOWN)):
        tid = by[("c0", idx)]
        _start(svc, tid)
        _finish(svc, tid, outcome=TaskOutcome.SUCCESS, interv=interv)
    got = [is_autonomous_success(svc.get_trial(by[("c0", i)])) for i in range(3)]
    assert got == [True, False, False]
    # teleoperated with intervention none and a success must never be autonomous
    for idx in range(3):
        tid = by[("c1", idx)]
        _start(svc, tid)
        _finish(svc, tid, outcome=TaskOutcome.SUCCESS, interv=Intervention.NONE)
    assert not any(is_autonomous_success(svc.get_trial(by[("c1", i)])) for i in range(3))
    m = compute_metrics(svc.list_trials(trials[0].session_id))
    assert m.overall.autonomous_successes == 1 and m.overall.success_per_attempt.k == 1


def test_score_without_stating_intervention_stays_unknown_and_not_autonomous(tmp_path: Path) -> None:
    svc, _, trials = _session(tmp_path, _cfg())
    tid = trials[0].trial_id
    _completed_unscored(svc, tid)
    t = svc.score_trial(tid, TaskOutcome.SUCCESS, source=ScoreSource.OPERATOR_VIDEO, scorer="a")
    assert t.intervention == Intervention.UNKNOWN and not is_autonomous_success(t)


def test_quality_fail_success_not_autonomous(tmp_path: Path) -> None:
    svc, _, trials = _session(tmp_path, _cfg())
    tid = trials[0].trial_id
    _start(svc, tid)
    _finish(svc, tid, outcome=TaskOutcome.SUCCESS, interv=Intervention.NONE)
    svc.set_recording_quality(tid, RecordingQuality.FAIL, ["truncated_video"])
    assert not is_autonomous_success(svc.get_trial(tid))


def test_score_source_must_match_session_provenance(tmp_path: Path) -> None:
    svc, _, trials = _session(tmp_path, _cfg())
    tid = trials[0].trial_id
    _completed_unscored(svc, tid)
    with pytest.raises(ValueError):
        svc.score_trial(
            tid,
            TaskOutcome.SUCCESS,
            source=ScoreSource.PHYSICS_EVIDENCE,
            scorer="a",
            intervention=Intervention.NONE,
        )


def test_terminal_trial_artifact_hash_cannot_be_silently_replaced(tmp_path: Path) -> None:
    svc, _, trials = _session(tmp_path, _cfg())
    tid = trials[0].trial_id
    _start(svc, tid)
    _finish(svc, tid)
    a = ArtifactRef(
        role=ArtifactRole.VIDEO,
        relpath="trials/x/video.mp4",
        sha256="a" * 64,
        size_bytes=1,
        status=ArtifactStatus.PRESENT,
    )
    svc.register_artifacts(tid, [a])
    with pytest.raises((InvalidTransitionError, ValueError)):
        svc.register_artifacts(tid, [a.model_copy(update={"sha256": "b" * 64})])


def test_quality_fail_cannot_be_flipped_to_pass_unaudited(tmp_path: Path) -> None:
    svc, s, trials = _session(tmp_path, _cfg())
    tid = trials[0].trial_id
    _start(svc, tid)
    _finish(svc, tid, outcome=TaskOutcome.SUCCESS, interv=Intervention.NONE)
    svc.set_recording_quality(tid, RecordingQuality.FAIL, ["truncated_video"])
    try:
        svc.set_recording_quality(tid, RecordingQuality.PASS, [])
    except (InvalidTransitionError, ValueError):
        return
    ev = [e for e in svc.list_events(s.session_id) if e["kind"] == "recording_quality"]
    assert "fail" in str(ev[-1]["detail"]), "overwrite of a FAIL quality did not record the previous value"


def test_device_lock_exclusive(tmp_path: Path) -> None:
    cfg = _cfg()
    svc, s1, _ = _session(tmp_path, cfg)
    s2 = svc.create_session("v2", Provenance.MOCK, "mock")
    svc.acquire_device("dev", s1.session_id)
    svc.acquire_device("dev", s1.session_id)  # idempotent
    with pytest.raises(DeviceBusyError):
        svc.acquire_device("dev", s2.session_id)
    assert not svc.release_device("dev", s2.session_id)  # non-owner cannot release
    assert svc.device_lock_holder("dev") == s1.session_id


# ---------------------------------------------------------------- planned trials never vanish
def test_planned_trials_never_vanish_from_manifest_or_metrics(tmp_path: Path) -> None:
    svc, s, trials = _session(tmp_path, _cfg(2, 2, 2))  # 8 planned
    for t in trials[:3]:
        _start(svc, t.trial_id)
        _finish(svc, t.trial_id, outcome=TaskOutcome.SUCCESS, interv=Intervention.NONE)
    man = svc.export_manifest(s.session_id)
    assert len(man.trials) == 8
    assert sum(1 for t in man.trials if t.state == TrialState.PLANNED) == 5
    m = compute_metrics(svc.list_trials(s.session_id))
    assert (m.overall.planned, m.overall.attempted, m.overall.not_attempted) == (8, 3, 5)
    assert sum(g.planned for g in m.by_controller_condition) == 8
    assert sum(g.planned for g in m.by_condition) == 8
    assert m.overall.success_per_attempt.n == 3  # not 8: never-attempted trials are not in this denominator


# ---------------------------------------------------------------- independent hand computation (contracts s5)
def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def test_denominators_by_hand(tmp_path: Path) -> None:
    cfg = _cfg(2, 1, 5)  # 10 planned trials
    svc, s, trials = _session(tmp_path, cfg)
    t = [x.trial_id for x in trials]
    for i in range(8):
        _start(svc, t[i])
    # T0 autonomous success, quality pass
    _finish(svc, t[0], outcome=TaskOutcome.SUCCESS, interv=Intervention.NONE)
    # T1 success none but recording quality FAIL (scored, excluded from evaluable, not autonomous)
    _finish(svc, t[1], outcome=TaskOutcome.SUCCESS, interv=Intervention.NONE)
    # T2 assisted success
    _finish(svc, t[2], outcome=TaskOutcome.SUCCESS, interv=Intervention.ASSISTED)
    # T3 failure (timeout), none
    _finish(svc, t[3], TerminationReason.TIMEOUT, TaskOutcome.FAILURE, Intervention.NONE)
    # T4 success with unknown intervention
    _finish(svc, t[4], outcome=TaskOutcome.SUCCESS, interv=Intervention.UNKNOWN)
    # T5 infra failure
    _finish(svc, t[5], TerminationReason.INFRA_FAILURE)
    # T6 operator abort (not infra)
    _finish(svc, t[6], TerminationReason.OPERATOR_ABORT)
    # T7 completed, never scored
    _finish(svc, t[7])
    for i in (0, 2, 3, 4):
        svc.set_recording_quality(t[i], RecordingQuality.PASS)
    svc.set_recording_quality(t[1], RecordingQuality.FAIL, ["truncated_video"])
    # T8, T9 stay planned

    g = compute_metrics(svc.list_trials(s.session_id)).overall
    assert (g.planned, g.attempted, g.not_attempted) == (10, 8, 2)
    assert (g.completed, g.failed, g.aborted) == (6, 1, 1)
    assert g.unscored == 3  # T5, T6, T7 (T8/T9 were never attempted)
    assert g.evaluable == 4  # T0,T2,T3,T4 (T1 excluded by quality fail)
    assert g.quality_excluded == 1
    assert g.autonomous_successes == 1
    assert (g.assisted_successes, g.unknown_intervention_successes) == (1, 1)
    assert (g.success_per_attempt.k, g.success_per_attempt.n) == (1, 8)
    assert (g.success_per_evaluable.k, g.success_per_evaluable.n) == (1, 4)
    assert (g.intervention_rate.k, g.intervention_rate.n) == (1, 8)
    assert (g.infra_abort_rate.k, g.infra_abort_rate.n) == (1, 8)  # only INFRA_FAILURE; abort is not infra
    assert (g.recording_pass_rate.k, g.recording_pass_rate.n) == (4, 8)
    lo, hi = wilson(1, 8)
    assert g.success_per_attempt.ci_low == pytest.approx(lo, abs=2e-3)
    assert g.success_per_attempt.ci_high == pytest.approx(hi, abs=2e-3)
    lo, hi = wilson(1, 4)
    assert g.success_per_evaluable.ci_low == pytest.approx(lo, abs=2e-3)
    assert g.success_per_evaluable.ci_high == pytest.approx(hi, abs=2e-3)
    # artifacts: nothing registered -> each attempted trial expects video+trace and has none
    assert (g.artifacts.expected, g.artifacts.present_with_hash, g.artifacts.missing) == (16, 0, 16)
