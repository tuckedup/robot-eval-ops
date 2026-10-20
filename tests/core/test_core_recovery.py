from __future__ import annotations

import pytest

from conftest import FakeAdapter, NoopController, make_config
from robotevalops.core.fault_interrupted import run_interrupted_runner_case
from robotevalops.core.runner import Runner
from robotevalops.core.service import EvalService
from robotevalops.errors import PreflightFailedError
from robotevalops.schemas import (
    ArtifactStatus,
    Provenance,
    QACode,
    SessionState,
    TaskOutcome,
    TerminationReason,
    TrialState,
)
from robotevalops.util import sha256_bytes

T = TrialState


def crash_mid_trial(home, provenance=Provenance.MOCK):
    svc = EvalService(home)
    backend = "mock" if provenance == Provenance.MOCK else "so101_lerobot"
    cfg = make_config(1, 3, 1, provenance=provenance, backend=backend)
    s = svc.create_session("c", provenance, backend, eval_config=cfg, device_id="arm0")
    trials = svc.plan_trials(s.session_id, cfg)
    svc.mark_preflight_passed(s.session_id)
    svc.transition_session(s.session_id, SessionState.RUNNING)
    # trial 0 finished, trial 1 dies while RUNNING, trial 2 never started
    t0, t1, t2 = trials
    for st in (T.PREFLIGHT, T.READY, T.RUNNING):
        svc.transition_trial(t0.trial_id, st)
    svc.record_trial_result(t0.trial_id, termination_reason=TerminationReason.TIMEOUT, duration_s=1.0)
    for st in (T.PREFLIGHT, T.READY):
        svc.transition_trial(t1.trial_id, st)
    svc.transition_trial(t1.trial_id, T.RUNNING, evidence={"pre": "crash"})
    d = svc.trial_dir(s.session_id, t1.trial_id)
    d.mkdir(parents=True)
    (d / "trace.jsonl").write_bytes(b"partial")
    svc.acquire_device("arm0", s.session_id)
    return s, t0, t1, t2


def test_recover_after_restart_preserves_evidence_and_gates_runner(tmp_path):
    home = tmp_path / "home"
    s, t0, t1, t2 = crash_mid_trial(home)
    svc = EvalService(home)  # restart: fresh instance, same db file
    assert [x.session_id for x in svc.find_interrupted()] == [s.session_id]
    recovered = svc.recover_interrupted(s.session_id)
    assert [t.trial_id for t in recovered] == [t1.trial_id]
    got = svc.get_trial(t1.trial_id)
    assert got.state == T.ABORTED and got.termination_reason == TerminationReason.INTERRUPTED_RUNNER
    assert got.task_outcome == TaskOutcome.UNSCORED and not got.is_autonomous_success
    assert got.evidence["pre"] == "crash"  # pre-crash evidence kept
    art = got.artifacts[0]
    assert art.status == ArtifactStatus.PRESENT and art.sha256 == sha256_bytes(b"partial")
    assert got.evidence["interrupted_runner"]["files_on_disk"] == [art.relpath]
    assert got.duration_s is None  # never measured, never invented
    # others untouched
    assert svc.get_trial(t0.trial_id).state == T.COMPLETED
    assert svc.get_trial(t2.trial_id).state == T.PLANNED
    sess = svc.get_session(s.session_id)
    assert sess.state == SessionState.PREFLIGHT and sess.requires_fresh_preflight
    assert svc.device_lock_holder("arm0") is None  # stale lock released
    assert svc.find_interrupted() == []

    ad = FakeAdapter()
    runner = Runner(svc, lambda _s: ad, NoopController)
    with pytest.raises(PreflightFailedError):
        runner.run_session(s.session_id)
    assert ad.episodes == 0

    svc.mark_preflight_passed(s.session_id)
    runner.run_session(s.session_id)
    assert ad.episodes == 1  # only the never-started trial; the aborted one is not resumed
    assert svc.get_trial(t1.trial_id).state == T.ABORTED
    assert svc.get_trial(t2.trial_id).state == T.COMPLETED


def test_recover_is_idempotent(tmp_path):
    home = tmp_path / "home"
    s, _t0, t1, _t2 = crash_mid_trial(home)
    svc = EvalService(home)
    first = svc.recover_interrupted(s.session_id)
    snapshot = svc.get_trial(t1.trial_id).model_dump()
    sess_snapshot = svc.get_session(s.session_id).model_dump()
    assert len(first) == 1
    assert svc.recover_interrupted(s.session_id) == []
    assert svc.get_trial(t1.trial_id).model_dump() == snapshot
    sess_after = svc.get_session(s.session_id).model_dump()
    sess_snapshot.pop("updated_at")
    sess_after.pop("updated_at")
    assert sess_after == sess_snapshot


def test_registered_but_missing_file_is_recorded_missing(tmp_path):
    home = tmp_path / "home"
    s, _t0, t1, _t2 = crash_mid_trial(home)
    svc = EvalService(home)
    from robotevalops.schemas import ArtifactRef, ArtifactRole

    svc.register_artifacts(
        t1.trial_id,
        [ArtifactRef(role=ArtifactRole.VIDEO, relpath=f"trials/{t1.trial_id}/video.mp4", sha256="a" * 64)],
    )
    svc.recover_interrupted(s.session_id)
    arts = {a.relpath.rsplit("/", 1)[1]: a for a in svc.get_trial(t1.trial_id).artifacts}
    assert arts["video.mp4"].status == ArtifactStatus.MISSING
    assert arts["trace.jsonl"].status == ArtifactStatus.PRESENT


def test_session_running_without_running_trial_is_still_interrupted(svc):
    cfg = make_config(1, 1, 1)
    s = svc.create_session("s", Provenance.MOCK, "mock", eval_config=cfg)
    svc.plan_trials(s.session_id, cfg)
    svc.mark_preflight_passed(s.session_id)
    svc.transition_session(s.session_id, SessionState.RUNNING)
    assert [x.session_id for x in svc.find_interrupted()] == [s.session_id]
    assert svc.recover_interrupted(s.session_id) == []
    got = svc.get_session(s.session_id)
    assert got.state == SessionState.PREFLIGHT and got.requires_fresh_preflight


def test_healthy_sessions_are_not_flagged(svc):
    cfg = make_config(1, 1, 1)
    s = svc.create_session("s", Provenance.MOCK, "mock", eval_config=cfg)
    svc.plan_trials(s.session_id, cfg)
    assert svc.find_interrupted() == []


def test_f10_fault_case_passes(tmp_path):
    r = run_interrupted_runner_case(tmp_path)
    assert r.case_id == "F10_interrupted_runner"
    assert r.expected_code == QACode.INTERRUPTED_RUNNER
    failed = [k for k, v in r.details["checks"].items() if not v]
    assert failed == []
    assert r.detected and r.evidence_preserved and r.misleading_success_prevented and r.passed
    assert r.detected_codes == ["interrupted_runner"]
