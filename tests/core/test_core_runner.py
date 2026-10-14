from __future__ import annotations

import threading

import pytest
from conftest import VIDEO_BYTES, FakeAdapter, NoopController, make_config

from robotevalops.core.runner import Runner
from robotevalops.errors import DeviceBusyError, HardwareRefusedError, PreflightFailedError
from robotevalops.schemas import (
    ArtifactStatus,
    Intervention,
    Provenance,
    QACode,
    QAFlag,
    QAReport,
    RecordingQuality,
    ScoreSource,
    SessionState,
    Severity,
    TaskOutcome,
    TerminationReason,
    TrialState,
)
from robotevalops.util import sha256_bytes

T = TrialState


def make_session(svc, behaviors, *, provenance=Provenance.MOCK, controllers=1, trials=1, names=None, **kw):
    names = names or list(behaviors)
    backend = (
        "mock"
        if provenance == Provenance.MOCK
        else ("pybullet_panda" if provenance == Provenance.SIMULATION else "so101_lerobot")
    )
    cfg = make_config(
        controllers, len(names), trials, provenance=provenance, backend=backend, condition_names=names
    )
    s = svc.create_session("s", provenance, backend, eval_config=cfg, **kw)
    svc.plan_trials(s.session_id, cfg)
    return s


def run(svc, session, adapter, **kw):
    runner = Runner(svc, lambda _s: adapter, NoopController, **kw)
    return runner, runner.run_session(session.session_id)


def by_cond(svc, session):
    return {t.condition_name: t for t in svc.list_trials(session.session_id)}


def test_success_failure_paths_and_scoring_sources(svc):
    s = make_session(svc, {"ok": "success", "bad": "failure"})
    ad = FakeAdapter({"ok": "success", "bad": "failure"})
    _, rep = run(svc, s, ad, qa_hook=lambda trial, _d: QAReport(subject=trial.trial_id))
    t = by_cond(svc, s)
    assert rep.final_session_state == SessionState.COMPLETED
    assert t["ok"].state == T.COMPLETED and t["ok"].task_outcome == TaskOutcome.SUCCESS
    assert t["ok"].score_source == ScoreSource.MOCK_FIXTURE and t["ok"].is_autonomous_success
    assert t["ok"].termination_reason == TerminationReason.SUCCESS_CRITERION_MET
    assert t["bad"].state == T.COMPLETED and t["bad"].task_outcome == TaskOutcome.FAILURE
    assert t["bad"].termination_reason == TerminationReason.TIMEOUT
    assert t["ok"].intervention == Intervention.NONE
    assert t["ok"].started_at is not None and t["ok"].reset_duration_s is not None
    assert ad.closed
    assert svc.get_session(s.session_id).state == SessionState.COMPLETED


def test_simulation_scores_with_physics_evidence(svc):
    s = make_session(svc, {"c": "success"}, provenance=Provenance.SIMULATION)
    run(svc, s, FakeAdapter({"c": "success"}, Provenance.SIMULATION))
    t = by_cond(svc, s)["c"]
    assert t.score_source == ScoreSource.PHYSICS_EVIDENCE and t.task_outcome == TaskOutcome.SUCCESS


def test_seed_passed_to_adapter_matches_trial_and_is_paired(svc):
    s = make_session(svc, {"a": "success", "b": "success"}, controllers=2, trials=1)
    ad = FakeAdapter()
    run(svc, s, ad)
    trials = svc.list_trials(s.session_id)
    assert [x for x in ad.seeds] == [(t.condition_name, t.seed) for t in trials]
    assert len({t.seed for t in trials if t.condition_name == "a"}) == 1


def test_assisted_intervention_is_not_autonomous_success(svc):
    s = make_session(svc, {"x": "assisted"})
    run(svc, s, FakeAdapter({"x": "assisted"}))
    t = by_cond(svc, s)["x"]
    assert t.intervention == Intervention.ASSISTED and t.task_outcome == TaskOutcome.SUCCESS
    assert not t.is_autonomous_success


def test_hardware_unjudged_stays_unscored_and_intervention_unknown(svc):
    s = make_session(svc, {"x": "hw_unjudged"}, provenance=Provenance.PHYSICAL_HARDWARE, device_id="arm0")
    svc.acknowledge_operator(s.session_id, "alice")
    svc.mark_preflight_passed(s.session_id)
    ad = FakeAdapter({"x": "hw_unjudged"}, Provenance.PHYSICAL_HARDWARE)
    run(svc, s, ad)
    t = by_cond(svc, s)["x"]
    assert t.state == T.COMPLETED and t.task_outcome == TaskOutcome.UNSCORED
    assert t.intervention == Intervention.UNKNOWN and not t.is_autonomous_success
    assert svc.device_lock_holder("arm0") is None


def test_infra_exception_is_failed_unscored_and_run_continues(svc):
    s = make_session(svc, {"boom": "infra_raise", "fine": "success"})
    _, rep = run(svc, s, FakeAdapter({"boom": "infra_raise", "fine": "success"}))
    t = by_cond(svc, s)
    assert t["boom"].state == T.FAILED and t["boom"].termination_reason == TerminationReason.INFRA_FAILURE
    assert t["boom"].task_outcome == TaskOutcome.UNSCORED and not t["boom"].is_autonomous_success
    assert "camera exploded" in t["boom"].evidence["exception"]
    assert t["fine"].state == T.COMPLETED
    assert rep.final_session_state == SessionState.COMPLETED
    # failed trial stays in the manifest and counts
    m = svc.export_manifest(s.session_id)
    assert len(m.trials) == 2 and {e.state for e in m.trials} == {T.FAILED, T.COMPLETED}
    # partial files recorded as evidence even though the adapter raised
    assert any(a.relpath.endswith("trace.jsonl") for a in t["boom"].artifacts)


def test_recording_failure_with_claimed_success_is_never_success(svc):
    s = make_session(svc, {"r": "recording_failure"})
    run(svc, s, FakeAdapter({"r": "recording_failure"}))
    t = by_cond(svc, s)["r"]
    assert t.state == T.FAILED and t.termination_reason == TerminationReason.RECORDING_FAILURE
    assert t.task_outcome == TaskOutcome.UNSCORED and t.evidence["error"] == "disk full"


def test_reset_failure_is_failed_infra_and_counted_as_attempt(svc):
    s = make_session(svc, {"r": "reset_raise"})
    run(svc, s, FakeAdapter({"r": "reset_raise"}))
    t = by_cond(svc, s)["r"]
    assert t.state == T.FAILED and t.termination_reason == TerminationReason.INFRA_FAILURE
    assert "reset failed" in t.evidence["error"] and t.is_attempted


def test_operator_abort_ends_session_aborted_rest_stay_planned(svc):
    names = ["a", "b", "c"]
    s = make_session(svc, {"b": "abort"}, names=names)
    _, rep = run(svc, s, FakeAdapter({"b": "abort"}))
    t = by_cond(svc, s)
    assert t["a"].state == T.COMPLETED and t["b"].state == T.ABORTED and t["c"].state == T.PLANNED
    assert t["b"].task_outcome == TaskOutcome.UNSCORED
    assert rep.final_session_state == SessionState.ABORTED


def test_preflight_failure_marks_failed_and_halts_with_fresh_preflight(svc):
    s = make_session(svc, {"a": "success", "b": "success"})
    ad = FakeAdapter(preflight_ok=False)
    _, rep = run(svc, s, ad)
    t = by_cond(svc, s)
    assert t["a"].state == T.FAILED and t["a"].termination_reason == TerminationReason.PREFLIGHT_FAILED
    assert t["a"].task_outcome == TaskOutcome.UNSCORED and ad.episodes == 0
    assert t["b"].state == T.PLANNED
    got = svc.get_session(s.session_id)
    assert got.state == SessionState.PREFLIGHT and got.requires_fresh_preflight
    assert rep.halted_reason == "preflight_failed"


def test_artifacts_hashed_and_registered(svc):
    s = make_session(svc, {"a": "success", "nv": "no_video"})
    run(svc, s, FakeAdapter({"nv": "no_video"}))
    t = by_cond(svc, s)
    arts = {a.relpath.rsplit("/", 1)[1]: a for a in t["a"].artifacts}
    video = arts["video.mp4"]
    assert video.status == ArtifactStatus.PRESENT and video.sha256 == sha256_bytes(VIDEO_BYTES)
    assert video.size_bytes == len(VIDEO_BYTES)
    assert video.relpath == f"trials/{t['a'].trial_id}/video.mp4"
    assert "controller.json" in arts and arts["controller.json"].sha256
    ctrl = (svc.trial_dir(s.session_id, t["a"].trial_id) / "controller.json").read_text()
    assert t["a"].controller_config_hash in ctrl
    missing = {a.relpath.rsplit("/", 1)[1]: a for a in t["nv"].artifacts}["video.mp4"]
    assert missing.status == ArtifactStatus.MISSING and missing.sha256 is None
    assert t["nv"].state == T.COMPLETED  # a missing video is flagged, the lifecycle is not rewritten


def test_qa_and_manifest_hooks(svc):
    s = make_session(svc, {"a": "success"})
    calls: list[str] = []

    def qa(trial, run_dir):
        assert run_dir == svc.run_dir(s.session_id)
        return QAReport(
            subject=trial.trial_id,
            flags=[QAFlag(code=QACode.MISSING_VIDEO, severity=Severity.ERROR, message="x")],
        )

    run(svc, s, FakeAdapter(), qa_hook=qa, manifest_hook=lambda sid: calls.append(sid))
    t = by_cond(svc, s)["a"]
    assert t.recording_quality == RecordingQuality.FAIL and t.qa_flags == ["missing_video"]
    assert not t.is_autonomous_success
    assert calls == [s.session_id]


def test_failing_hooks_do_not_break_the_run(svc):
    s = make_session(svc, {"a": "success"})

    def bad(*_a):
        raise RuntimeError("hook bug")

    _, rep = run(svc, s, FakeAdapter(), qa_hook=bad, manifest_hook=bad)
    assert rep.final_session_state == SessionState.COMPLETED
    kinds = [e["kind"] for e in svc.list_events(s.session_id)]
    assert "qa_hook_error" in kinds and "manifest_hook_error" in kinds


def test_max_trials_leaves_rest_planned_and_session_ready(svc):
    s = make_session(svc, {"a": "success", "b": "success", "c": "success"})
    runner, rep = run(svc, s, FakeAdapter())
    assert rep.final_session_state == SessionState.COMPLETED
    s2 = make_session(svc, {"a": "success", "b": "success", "c": "success"})
    ad = FakeAdapter()
    rep = Runner(svc, lambda _s: ad, NoopController).run_session(s2.session_id, max_trials=2)
    assert rep.final_session_state == SessionState.READY and ad.episodes == 2
    assert len(svc.list_trials(s2.session_id, T.PLANNED)) == 1
    ad2 = FakeAdapter()
    Runner(svc, lambda _s: ad2, NoopController).run_session(s2.session_id)
    assert ad2.episodes == 1 and svc.get_session(s2.session_id).state == SessionState.COMPLETED


def test_stop_request_aborts_running_trial_and_prevents_more(svc):
    s = make_session(svc, {"a": "block_until_stop", "b": "success"})
    ad = FakeAdapter({"a": "block_until_stop"})
    runner = Runner(svc, lambda _x: ad, NoopController, stop_poll_interval_s=0.01)
    result = {}
    th = threading.Thread(target=lambda: result.update(rep=runner.run_session(s.session_id)))
    th.start()
    assert ad.started.wait(10)
    assert svc.request_stop(s.session_id) is True
    assert svc.request_stop(s.session_id) is False  # idempotent
    th.join(15)
    assert not th.is_alive()
    t = by_cond(svc, s)
    assert t["a"].state == T.ABORTED and t["a"].termination_reason == TerminationReason.SOFTWARE_STOP_REQUEST
    assert t["a"].task_outcome == TaskOutcome.UNSCORED
    assert t["b"].state == T.PLANNED and ad.episodes == 1
    assert svc.get_session(s.session_id).state == SessionState.ABORTED
    assert ad.stop_calls >= 1


def test_stop_requested_before_run_starts_no_trial(svc):
    s = make_session(svc, {"a": "success"})
    svc.request_stop(s.session_id)
    ad = FakeAdapter()
    _, rep = run(svc, s, ad)
    assert ad.episodes == 0 and rep.final_session_state == SessionState.ABORTED
    assert by_cond(svc, s)["a"].state == T.PLANNED


def test_hardware_refused_without_ack_and_adapter_never_built(svc):
    s = make_session(svc, {"a": "success"}, provenance=Provenance.PHYSICAL_HARDWARE, device_id="arm0")
    svc.mark_preflight_passed(s.session_id)
    built = []
    runner = Runner(svc, lambda x: built.append(x) or FakeAdapter(), NoopController)
    with pytest.raises(HardwareRefusedError):
        runner.run_session(s.session_id)
    assert built == [] and svc.device_lock_holder("arm0") is None
    assert by_cond(svc, s)["a"].state == T.PLANNED


def test_hardware_requires_explicit_preflight_even_with_ack(svc):
    s = make_session(svc, {"a": "success"}, provenance=Provenance.PHYSICAL_HARDWARE, device_id="arm0")
    svc.acknowledge_operator(s.session_id, "alice")
    with pytest.raises(PreflightFailedError):
        Runner(svc, lambda _x: FakeAdapter(), NoopController).run_session(s.session_id)


def test_fresh_preflight_flag_blocks_run(svc):
    s = make_session(svc, {"a": "success"})
    svc.flag_fresh_preflight(s.session_id)
    ad = FakeAdapter()
    with pytest.raises(PreflightFailedError):
        run(svc, s, ad)
    assert ad.episodes == 0


def test_device_lock_overlap_and_release_on_exception(svc):
    a = make_session(svc, {"a": "success"}, provenance=Provenance.PHYSICAL_HARDWARE, device_id="arm0")
    b = make_session(svc, {"a": "success"}, provenance=Provenance.PHYSICAL_HARDWARE, device_id="arm0")
    for s in (a, b):
        svc.acknowledge_operator(s.session_id, "alice")
        svc.mark_preflight_passed(s.session_id)
    svc.acquire_device("arm0", a.session_id)  # another runner owns the arm
    with pytest.raises(DeviceBusyError):
        Runner(svc, lambda _x: FakeAdapter(), NoopController).run_session(b.session_id)
    assert svc.device_lock_holder("arm0") == a.session_id  # b did not steal or release it
    svc.release_device("arm0", a.session_id)

    def explode(_s):
        raise RuntimeError("adapter factory failed")

    with pytest.raises(RuntimeError):
        Runner(svc, explode, NoopController).run_session(b.session_id)
    assert svc.device_lock_holder("arm0") is None  # released in finally


def test_terminal_session_cannot_run_again(svc):
    s = make_session(svc, {"a": "success"})
    run(svc, s, FakeAdapter())
    with pytest.raises(PreflightFailedError):
        run(svc, s, FakeAdapter())


def test_gate_refusal_at_reset_is_not_an_attempt(svc):
    s = make_session(
        svc, {"a": "reset_refused", "b": "success"}, provenance=Provenance.PHYSICAL_HARDWARE, device_id="arm0"
    )
    svc.acknowledge_operator(s.session_id, "alice")
    svc.mark_preflight_passed(s.session_id)
    ad = FakeAdapter({"a": "reset_refused"}, Provenance.PHYSICAL_HARDWARE)
    with pytest.raises(HardwareRefusedError):
        run(svc, s, ad)
    t = by_cond(svc, s)
    assert all(x.started_at is None for x in t.values())  # nothing counted as attempted
    assert all(x.state in (T.PLANNED, T.PREFLIGHT) for x in t.values())
    assert not any(x.termination_reason == TerminationReason.INFRA_FAILURE for x in t.values())
    got = svc.get_session(s.session_id)
    assert got.state == SessionState.READY and not got.requires_fresh_preflight
    assert svc.device_lock_holder("arm0") is None and ad.closed and ad.episodes == 0
    # once the gate is satisfied the same trials run normally
    ad2 = FakeAdapter({}, Provenance.PHYSICAL_HARDWARE)
    run(svc, s, ad2)
    assert ad2.episodes == 2
