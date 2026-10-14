from __future__ import annotations

import threading
import uuid

import pytest
from conftest import make_config

from robotevalops.core.service import EvalService
from robotevalops.errors import (
    DeviceBusyError,
    DuplicateIdError,
    InvalidTransitionError,
    NotFoundError,
    PathTraversalError,
    ScoreProtectionError,
)
from robotevalops.lifecycle_rules import SESSION_TRANSITIONS, TRIAL_TRANSITIONS
from robotevalops.schemas import (
    ArtifactRef,
    ArtifactRole,
    ArtifactStatus,
    ControllerSpec,
    ControllerType,
    Intervention,
    Provenance,
    RecordingQuality,
    ScoreSource,
    SessionState,
    TaskOutcome,
    TerminationReason,
    TrialState,
)

T = TrialState
S = SessionState
_TERM = {
    T.COMPLETED: TerminationReason.TIMEOUT,
    T.FAILED: TerminationReason.INFRA_FAILURE,
    T.ABORTED: TerminationReason.OPERATOR_ABORT,
}
_PATH = {
    T.PLANNED: [],
    T.PREFLIGHT: [T.PREFLIGHT],
    T.READY: [T.PREFLIGHT, T.READY],
    T.RUNNING: [T.PREFLIGHT, T.READY, T.RUNNING],
    T.COMPLETED: [T.PREFLIGHT, T.READY, T.RUNNING, T.COMPLETED],
    T.FAILED: [T.PREFLIGHT, T.FAILED],
    T.ABORTED: [T.ABORTED],
}


def drive(svc: EvalService, tid: str, target: T) -> None:
    for st in _PATH[target]:
        extra = {"termination_reason": _TERM[st]} if st in _TERM else {}
        svc.transition_trial(tid, st, **extra)


def to_running(svc: EvalService, tid: str) -> None:
    drive(svc, tid, T.RUNNING)


def finish_ok(
    svc,
    tid,
    *,
    intervention=Intervention.NONE,
    outcome=TaskOutcome.SUCCESS,
    quality=RecordingQuality.PASS,
):
    to_running(svc, tid)
    return svc.record_trial_result(
        tid,
        termination_reason=TerminationReason.SUCCESS_CRITERION_MET,
        duration_s=3.0,
        task_outcome=outcome,
        score_source=ScoreSource.MOCK_FIXTURE,
        intervention=intervention,
        recording_quality=quality,
    )


# ------------------------------------------------------------------ transitions
@pytest.mark.parametrize(("old", "new"), [(a, b) for a in T for b in T])
def test_trial_transition_matrix(svc, planned, old, new):
    _, trials, _ = planned
    tid = trials[0].trial_id
    drive(svc, tid, old)
    extra = {"termination_reason": _TERM[new]} if new in _TERM else {}
    if new in TRIAL_TRANSITIONS[old]:
        rec = svc.transition_trial(tid, new, **extra)
        assert rec.state == new
        if new == T.RUNNING:
            assert rec.started_at is not None
        if new in _TERM:
            assert rec.ended_at is not None
            assert rec.task_outcome == TaskOutcome.UNSCORED
    else:
        with pytest.raises(InvalidTransitionError):
            svc.transition_trial(tid, new, **extra)
        assert svc.get_trial(tid).state == old  # unchanged


@pytest.mark.parametrize(("old", "new"), [(a, b) for a in S for b in S])
def test_session_transition_matrix(svc, old, new):
    s = svc.create_session("s", Provenance.MOCK, "mock")
    path = {
        S.PLANNED: [],
        S.PREFLIGHT: [S.PREFLIGHT],
        S.READY: [S.PREFLIGHT, S.READY],
        S.RUNNING: [S.PREFLIGHT, S.READY, S.RUNNING],
        S.COMPLETED: [S.PREFLIGHT, S.READY, S.RUNNING, S.COMPLETED],
        S.FAILED: [S.PREFLIGHT, S.FAILED],
        S.ABORTED: [S.ABORTED],
    }[old]
    for st in path:
        svc.transition_session(s.session_id, st)
    if new in SESSION_TRANSITIONS[old]:
        assert svc.transition_session(s.session_id, new).state == new
    else:
        with pytest.raises(InvalidTransitionError):
            svc.transition_session(s.session_id, new)


def test_running_to_preflight_sets_fresh_preflight_flag(svc):
    s = svc.create_session("s", Provenance.MOCK, "mock")
    sid = s.session_id
    for st in (S.PREFLIGHT, S.READY, S.RUNNING, S.PREFLIGHT):
        svc.transition_session(sid, st)
    assert svc.get_session(sid).requires_fresh_preflight is True
    svc.mark_preflight_passed(sid)
    got = svc.get_session(sid)
    assert got.requires_fresh_preflight is False and got.state == S.READY


def test_terminal_trial_is_immutable(svc, planned):
    _, trials, _ = planned
    tid = trials[0].trial_id
    finish_ok(svc, tid)
    for new in T:
        with pytest.raises(InvalidTransitionError):
            svc.transition_trial(tid, new, termination_reason=TerminationReason.TIMEOUT)
    with pytest.raises(InvalidTransitionError):
        svc.record_trial_result(tid, termination_reason=TerminationReason.TIMEOUT, duration_s=1.0)


def test_terminal_session_is_immutable(svc):
    s = svc.create_session("s", Provenance.MOCK, "mock")
    svc.transition_session(s.session_id, S.ABORTED)
    for new in S:
        with pytest.raises(InvalidTransitionError):
            svc.transition_session(s.session_id, new)


def test_termination_reason_must_match_terminal_state(svc, planned):
    _, trials, _ = planned
    tid = trials[0].trial_id
    to_running(svc, tid)
    with pytest.raises(InvalidTransitionError):
        svc.transition_trial(tid, T.COMPLETED, termination_reason=TerminationReason.INFRA_FAILURE)
    with pytest.raises(InvalidTransitionError):
        svc.transition_trial(tid, T.FAILED, termination_reason=TerminationReason.SUCCESS_CRITERION_MET)
    with pytest.raises(TypeError):
        svc.transition_trial(tid, T.COMPLETED, task_outcome=TaskOutcome.SUCCESS)


# ------------------------------------------------------------------ ids, planning
def test_ids_are_uuid4_and_unique(svc, planned):
    s, trials, _ = planned
    assert uuid.UUID(s.session_id).version == 4
    ids = {t.trial_id for t in trials}
    assert len(ids) == 2
    assert all(uuid.UUID(i).version == 4 for i in ids)


def test_duplicate_session_id_rejected(svc):
    svc.create_session("a", Provenance.MOCK, "mock", session_id="fixed-id")
    with pytest.raises(DuplicateIdError):
        svc.create_session("b", Provenance.MOCK, "mock", session_id="fixed-id")


def test_duplicate_trial_id_rejected(svc, planned):
    _, trials, _ = planned
    with pytest.raises(DuplicateIdError), svc.db.tx() as c:
        svc._insert_trial(c, trials[0])


def test_plan_is_100_trials_and_cannot_be_replanned(svc):
    cfg = make_config(2, 5, 10)
    assert cfg.planned_count == 100
    s = svc.create_session("big", Provenance.MOCK, "mock", eval_config=cfg)
    out = svc.plan_trials(s.session_id, cfg)
    assert len(out) == 100
    assert [t.schedule_position for t in svc.list_trials(s.session_id)] == list(range(100))
    with pytest.raises(DuplicateIdError):
        svc.plan_trials(s.session_id, cfg)


def test_plan_rejects_mismatched_provenance(svc):
    s = svc.create_session("s", Provenance.MOCK, "mock")
    with pytest.raises(ValueError):
        svc.plan_trials(s.session_id, make_config(provenance=Provenance.SIMULATION))


def test_planned_trials_store_provenance_and_controller_type_separately(svc):
    cfg = make_config(1, 1, 1)
    tele = ControllerSpec(controller_id="human", type=ControllerType.TELEOPERATED, version="1")
    cfg = cfg.model_copy(update={"controllers": [tele]})
    s = svc.create_session("s", Provenance.MOCK, "mock", eval_config=cfg)
    (t,) = svc.plan_trials(s.session_id, cfg)
    got = svc.get_trial(t.trial_id)
    assert got.provenance == Provenance.MOCK and got.controller_type == ControllerType.TELEOPERATED
    assert got.controller_config_hash == tele.config_hash


def test_get_missing_raises_not_found(svc):
    with pytest.raises(NotFoundError):
        svc.get_session("nope")
    with pytest.raises(NotFoundError):
        svc.get_trial("nope")


# ------------------------------------------------------------------ results, scoring
def test_record_result_success_is_autonomous(svc, planned):
    _, trials, _ = planned
    t = finish_ok(svc, trials[0].trial_id)
    assert t.state == T.COMPLETED and t.task_outcome == TaskOutcome.SUCCESS
    assert t.is_autonomous_success
    assert t.duration_s == 3.0 and t.ended_at is not None


@pytest.mark.parametrize("iv", [Intervention.ASSISTED, Intervention.UNKNOWN])
def test_non_none_intervention_is_never_autonomous_success(svc, planned, iv):
    _, trials, _ = planned
    t = finish_ok(svc, trials[0].trial_id, intervention=iv)
    assert t.task_outcome == TaskOutcome.SUCCESS
    assert not t.is_autonomous_success


def test_teleoperated_success_is_not_autonomous(svc):
    cfg = make_config(1, 1, 1)
    cfg = cfg.model_copy(
        update={
            "controllers": [
                ControllerSpec(controller_id="human", type=ControllerType.TELEOPERATED, version="1")
            ]
        }
    )
    s = svc.create_session("s", Provenance.MOCK, "mock", eval_config=cfg)
    (t,) = svc.plan_trials(s.session_id, cfg)
    rec = finish_ok(svc, t.trial_id)
    assert rec.task_outcome == TaskOutcome.SUCCESS and not rec.is_autonomous_success


def test_quality_fail_removes_autonomous_success(svc, planned):
    _, trials, _ = planned
    tid = trials[0].trial_id
    assert finish_ok(svc, tid).is_autonomous_success
    rec = svc.set_recording_quality(tid, RecordingQuality.FAIL, ["missing_video", "missing_video"])
    assert rec.qa_flags == ["missing_video"]
    assert not rec.is_autonomous_success


def test_failed_infra_trial_stays_unscored_and_in_manifest(svc, planned):
    s, trials, _ = planned
    tid = trials[0].trial_id
    to_running(svc, tid)
    with pytest.raises(ValueError):  # an infra failure can never carry a success
        svc.record_trial_result(
            tid,
            termination_reason=TerminationReason.INFRA_FAILURE,
            duration_s=1.0,
            task_outcome=TaskOutcome.SUCCESS,
            score_source=ScoreSource.MOCK_FIXTURE,
        )
    assert svc.get_trial(tid).state == T.RUNNING  # nothing was written
    rec = svc.record_trial_result(tid, termination_reason=TerminationReason.RECORDING_FAILURE, duration_s=1.0)
    assert rec.state == T.FAILED and rec.task_outcome == TaskOutcome.UNSCORED
    assert not rec.is_autonomous_success
    with pytest.raises(InvalidTransitionError):
        svc.score_trial(tid, TaskOutcome.SUCCESS, source=ScoreSource.OPERATOR_VIDEO, scorer="op")
    m = svc.export_manifest(s.session_id)
    entry = next(e for e in m.trials if e.trial_id == tid)
    assert entry.state == T.FAILED and entry.task_outcome == TaskOutcome.UNSCORED
    assert len(svc.list_trials(s.session_id, T.FAILED)) == 1


def test_result_requires_source_for_outcome(svc, planned):
    _, trials, _ = planned
    to_running(svc, trials[0].trial_id)
    with pytest.raises(ValueError):
        svc.record_trial_result(
            trials[0].trial_id,
            termination_reason=TerminationReason.TIMEOUT,
            duration_s=1.0,
            task_outcome=TaskOutcome.FAILURE,
        )


def test_hardware_style_trial_stays_unscored_until_scored(svc, planned):
    _, trials, _ = planned
    tid = trials[0].trial_id
    to_running(svc, tid)
    rec = svc.record_trial_result(
        tid,
        termination_reason=TerminationReason.SUCCESS_CRITERION_MET,
        duration_s=5.0,
        intervention=Intervention.UNKNOWN,
    )
    assert rec.task_outcome == TaskOutcome.UNSCORED and rec.state == T.COMPLETED
    scored = svc.score_trial(
        tid,
        TaskOutcome.SUCCESS,
        source=ScoreSource.OPERATOR_VIDEO,
        scorer="alice",
        intervention=Intervention.NONE,
    )
    assert scored.task_outcome == TaskOutcome.SUCCESS
    assert not scored.is_autonomous_success  # QA never ran: unverified evidence is not verified success
    verified = svc.set_recording_quality(tid, RecordingQuality.PASS)
    assert verified.is_autonomous_success


def test_score_protection(svc, planned):
    _, trials, _ = planned
    tid = trials[0].trial_id
    finish_ok(svc, tid)
    with pytest.raises(ScoreProtectionError):
        svc.score_trial(tid, TaskOutcome.FAILURE, source=ScoreSource.OPERATOR_VIDEO, scorer="bob")
    assert svc.get_trial(tid).task_outcome == TaskOutcome.SUCCESS


def test_edit_score_requires_reason_and_logs_before_after(svc, planned):
    _, trials, _ = planned
    tid = trials[0].trial_id
    finish_ok(svc, tid)
    for bad in ("", "   "):
        with pytest.raises(ValueError):
            svc.edit_score(
                tid, TaskOutcome.FAILURE, source=ScoreSource.OPERATOR_VIDEO, editor="e", reason=bad
            )
    assert svc.list_score_edits(tid) == []
    edit = svc.edit_score(
        tid,
        TaskOutcome.FAILURE,
        intervention=Intervention.ASSISTED,
        source=ScoreSource.OPERATOR_VIDEO,
        editor="rev",
        reason="video shows a push",
    )
    assert (edit.before_outcome, edit.after_outcome) == (TaskOutcome.SUCCESS, TaskOutcome.FAILURE)
    assert (edit.before_intervention, edit.after_intervention) == (Intervention.NONE, Intervention.ASSISTED)
    assert (edit.before_source, edit.after_source) == (ScoreSource.MOCK_FIXTURE, ScoreSource.OPERATOR_VIDEO)
    got = svc.get_trial(tid)
    assert got.task_outcome == TaskOutcome.FAILURE and got.intervention == Intervention.ASSISTED
    logged = svc.list_score_edits(tid)
    assert len(logged) == 1 and logged[0].reason == "video shows a push" and logged[0].editor == "rev"
    svc.edit_score(
        tid, TaskOutcome.SUCCESS, source=ScoreSource.OPERATOR_VIDEO, editor="rev2", reason="re-check"
    )
    second = svc.list_score_edits(tid)[1]
    assert (
        second.before_outcome == TaskOutcome.FAILURE and second.before_intervention == Intervention.ASSISTED
    )


def test_concurrent_scoring_exactly_one_wins(svc, planned):
    _, trials, _ = planned
    tid = trials[0].trial_id
    to_running(svc, tid)
    svc.record_trial_result(tid, termination_reason=TerminationReason.TIMEOUT, duration_s=30.0)
    barrier = threading.Barrier(2)
    results: list[str] = []

    def worker(outcome: TaskOutcome, who: str) -> None:
        barrier.wait()
        try:
            svc.score_trial(tid, outcome, source=ScoreSource.OPERATOR_VIDEO, scorer=who)
            results.append("ok")
        except ScoreProtectionError:
            results.append("protected")

    ths = [
        threading.Thread(target=worker, args=(TaskOutcome.SUCCESS, "a")),
        threading.Thread(target=worker, args=(TaskOutcome.FAILURE, "b")),
    ]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    assert sorted(results) == ["ok", "protected"]
    assert svc.get_trial(tid).task_outcome in (TaskOutcome.SUCCESS, TaskOutcome.FAILURE)


# ------------------------------------------------------------------ artifacts / manifest
def test_register_artifacts_upserts_and_validates(svc, planned):
    _, trials, _ = planned
    tid = trials[0].trial_id
    a = ArtifactRef(role=ArtifactRole.VIDEO, relpath="trials/x/video.mp4", sha256="a" * 64, size_bytes=3)
    svc.register_artifacts(tid, [a])
    svc.register_artifacts(tid, [a.model_copy(update={"sha256": "b" * 64})])
    arts = svc.get_trial(tid).artifacts
    assert len(arts) == 1 and arts[0].sha256 == "b" * 64
    with pytest.raises(DuplicateIdError):
        svc.register_artifacts(tid, [a, a])
    with pytest.raises(PathTraversalError):
        svc.register_artifacts(tid, [a.model_copy(update={"relpath": "../evil"})])


def test_manifest_covers_every_planned_trial_with_calibration_ref(svc):
    cfg = make_config(1, 2, 2, provenance=Provenance.PHYSICAL_HARDWARE, backend="so101_lerobot")
    s = svc.create_session(
        "hw",
        Provenance.PHYSICAL_HARDWARE,
        "so101_lerobot",
        device_id="arm0",
        calibration_ref="calib/so101.json",
        eval_config=cfg,
    )
    trials = svc.plan_trials(s.session_id, cfg)
    to_running(svc, trials[0].trial_id)
    m = svc.export_manifest(s.session_id)
    assert len(m.trials) == 4
    assert {e.state for e in m.trials} == {T.RUNNING, T.PLANNED}
    assert all(e.calibration_ref == "calib/so101.json" for e in m.trials)
    assert m.provenance == Provenance.PHYSICAL_HARDWARE and m.eval_config_hash == cfg.config_hash


# ------------------------------------------------------------------ stop, locks, restart
def test_stop_request_is_idempotent_and_persisted(svc, tmp_path):
    s = svc.create_session("s", Provenance.MOCK, "mock")
    assert svc.is_stop_requested(s.session_id) is False
    assert svc.request_stop(s.session_id) is True
    assert svc.request_stop(s.session_id) is False
    assert EvalService(tmp_path / "home").is_stop_requested(s.session_id) is True


def test_device_lock_overlap_and_release(svc):
    a = svc.create_session("a", Provenance.PHYSICAL_HARDWARE, "so101_lerobot", device_id="arm0")
    b = svc.create_session("b", Provenance.PHYSICAL_HARDWARE, "so101_lerobot", device_id="arm0")
    svc.acquire_device("arm0", a.session_id)
    svc.acquire_device("arm0", a.session_id)  # re-acquire by owner is a no-op
    with pytest.raises(DeviceBusyError):
        svc.acquire_device("arm0", b.session_id)
    assert svc.release_device("arm0", b.session_id) is False  # not the owner
    assert svc.device_lock_holder("arm0") == a.session_id
    assert svc.release_device("arm0", a.session_id) is True
    svc.acquire_device("arm0", b.session_id)


def test_state_survives_new_service_instance(svc, planned, tmp_path):
    s, trials, _ = planned
    to_running(svc, trials[0].trial_id)
    again = EvalService(tmp_path / "home")
    assert again.get_trial(trials[0].trial_id).state == T.RUNNING
    assert len(again.list_trials(s.session_id)) == 2
    assert again.db.schema_version() == 1


def test_acknowledge_operator(svc):
    s = svc.create_session("hw", Provenance.PHYSICAL_HARDWARE, "so101_lerobot", device_id="arm0")
    assert s.operator_ack_at is None
    with pytest.raises(ValueError):
        svc.acknowledge_operator(s.session_id, " ")
    got = svc.acknowledge_operator(s.session_id, "alice")
    assert got.operator_ack_at is not None and got.operator == "alice"


# ------------------------------------------------------------------ VF-04 score source matrix
_ALLOWED = {
    Provenance.MOCK: {ScoreSource.MOCK_FIXTURE, ScoreSource.OPERATOR_VIDEO},
    Provenance.SIMULATION: {ScoreSource.PHYSICS_EVIDENCE, ScoreSource.OPERATOR_VIDEO},
    Provenance.IMPORTED_REAL_RECORDING: {ScoreSource.IMPORTED_LABEL, ScoreSource.OPERATOR_VIDEO},
    Provenance.PHYSICAL_HARDWARE: {ScoreSource.OPERATOR_VIDEO},
}


@pytest.mark.parametrize("prov", list(Provenance))
@pytest.mark.parametrize("src", [x for x in ScoreSource if x != ScoreSource.NONE])
def test_score_source_matrix(svc, prov, src):
    backend = "mock" if prov == Provenance.MOCK else "other"
    cfg = make_config(1, 1, 1, provenance=prov, backend=backend)
    s = svc.create_session("m", prov, backend)
    (t,) = svc.plan_trials(s.session_id, cfg.model_copy(update={"backend": backend}))
    to_running(svc, t.trial_id)
    svc.record_trial_result(t.trial_id, termination_reason=TerminationReason.TIMEOUT, duration_s=1.0)
    if src in _ALLOWED[prov]:
        assert svc.score_trial(t.trial_id, TaskOutcome.SUCCESS, source=src, scorer="x").score_source == src
    else:
        with pytest.raises(ValueError):
            svc.score_trial(t.trial_id, TaskOutcome.SUCCESS, source=src, scorer="x")
        assert svc.get_trial(t.trial_id).task_outcome == TaskOutcome.UNSCORED


def test_edit_score_and_record_result_enforce_source_matrix(svc, planned):
    _, trials, _ = planned
    tid = trials[0].trial_id
    finish_ok(svc, tid)
    with pytest.raises(ValueError):
        svc.edit_score(tid, TaskOutcome.FAILURE, source=ScoreSource.PHYSICS_EVIDENCE, editor="e", reason="r")
    to_running(svc, trials[1].trial_id)
    with pytest.raises(ValueError):
        svc.record_trial_result(
            trials[1].trial_id,
            termination_reason=TerminationReason.TIMEOUT,
            duration_s=1.0,
            task_outcome=TaskOutcome.FAILURE,
            score_source=ScoreSource.PHYSICS_EVIDENCE,
        )


# ------------------------------------------------------------------ VF-05 / VF-06 audit
def test_terminal_artifact_hash_replacement_needs_actor_and_reason_and_is_audited(svc, planned):
    s, trials, _ = planned
    tid = trials[0].trial_id
    finish_ok(svc, tid)
    a = ArtifactRef(
        role=ArtifactRole.VIDEO,
        relpath="trials/x/video.mp4",
        sha256="a" * 64,
        size_bytes=1,
        status=ArtifactStatus.PRESENT,
    )
    svc.register_artifacts(tid, [a])
    b = a.model_copy(update={"sha256": "b" * 64, "size_bytes": 2})
    with pytest.raises(ValueError):
        svc.register_artifacts(tid, [b])
    assert svc.get_trial(tid).artifacts[0].sha256 == "a" * 64
    svc.register_artifacts(tid, [b], actor="alice", reason="re-encoded after review")
    ev = [e for e in svc.list_events(s.session_id) if e["kind"] == "artifact_changed"]
    assert len(ev) == 1
    ch = ev[0]["detail"]["changes"][0]
    assert (
        ch["previous_sha256"] == "a" * 64 and ch["new_sha256"] == "b" * 64 and ch["previous_size_bytes"] == 1
    )
    assert ev[0]["detail"]["actor"] == "alice"


def test_mismatch_status_update_is_allowed_and_audited(svc, planned):
    s, trials, _ = planned
    tid = trials[0].trial_id
    finish_ok(svc, tid)
    a = ArtifactRef(
        role=ArtifactRole.VIDEO,
        relpath="v.mp4",
        sha256="a" * 64,
        size_bytes=1,
        status=ArtifactStatus.UPLOADED,
    )
    svc.register_artifacts(tid, [a])
    svc.register_artifacts(
        tid, [a.model_copy(update={"sha256": "c" * 64, "status": ArtifactStatus.MISMATCH})]
    )
    assert svc.get_trial(tid).artifacts[0].status == ArtifactStatus.MISMATCH
    ev = [e for e in svc.list_events(s.session_id) if e["kind"] == "artifact_changed"]
    assert ev[0]["detail"]["changes"][0]["previous_status"] == "uploaded"


def test_quality_fail_to_pass_needs_actor_and_reason_and_records_previous(svc, planned):
    s, trials, _ = planned
    tid = trials[0].trial_id
    finish_ok(svc, tid)
    svc.set_recording_quality(tid, RecordingQuality.FAIL, ["truncated_video"])  # first set: no reason needed
    with pytest.raises(ValueError):
        svc.set_recording_quality(tid, RecordingQuality.PASS, [])
    with pytest.raises(ValueError):
        svc.set_recording_quality(tid, RecordingQuality.PASS, [], actor="bob", reason=" ")
    assert svc.get_trial(tid).recording_quality == RecordingQuality.FAIL
    svc.set_recording_quality(tid, RecordingQuality.PASS, [], actor="bob", reason="re-inspected video, ok")
    ev = [e for e in svc.list_events(s.session_id) if e["kind"] == "recording_quality"]
    last = ev[-1]["detail"]
    assert (
        last["previous_quality"] == "fail"
        and last["actor"] == "bob"
        and last["previous_flags"] == ["truncated_video"]
    )
    # fail -> fail (re-run of the same verdict) needs nothing
    svc.set_recording_quality(tid, RecordingQuality.FAIL, ["x"])
