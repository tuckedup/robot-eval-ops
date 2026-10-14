"""Audit A1: a crashed/absent/interrupted QA must never produce verified autonomous success."""

from __future__ import annotations

import pytest
from conftest import FakeAdapter, NoopController
from test_core_runner import by_cond, make_session, run

from robotevalops.core.runner import Runner
from robotevalops.metrics.compute import compute_group
from robotevalops.metrics.failures import failure_class
from robotevalops.schemas import QACode, QAReport, RecordingQuality, TaskOutcome


def _raising(*_a):
    raise OSError("disk full while writing qa report")


def _verified(svc, s):
    return compute_group(svc.list_trials(s.session_id))


def test_raising_qa_hook_is_error_not_success(svc):
    s = make_session(svc, {"a": "success"})
    run(svc, s, FakeAdapter(), qa_hook=_raising)
    t = by_cond(svc, s)["a"]
    assert t.task_outcome == TaskOutcome.SUCCESS  # raw outcome preserved
    assert t.recording_quality == RecordingQuality.ERROR
    assert t.qa_flags == [QACode.QA_EXECUTION_ERROR.value]
    assert "OSError" in t.evidence["qa_error"]
    assert not t.is_autonomous_success
    g = _verified(svc, s)
    assert (g.attempted, g.raw_task_successes, g.unverified_successes) == (1, 1, 1)
    assert (g.evaluable, g.autonomous_successes, g.recording_qa_error) == (0, 0, 1)
    assert g.success_per_attempt.k == 0 and g.success_per_attempt.n == 1  # denominator keeps the attempt
    assert any("QA ERRORS" in w for w in g.warnings)
    assert failure_class(t) == "unverified_success"


def test_absent_qa_hook_is_unverified(svc):
    s = make_session(svc, {"a": "success"})
    run(svc, s, FakeAdapter())
    t = by_cond(svc, s)["a"]
    assert t.recording_quality == RecordingQuality.UNCHECKED and not t.is_autonomous_success
    g = _verified(svc, s)
    assert g.evaluable == 0 and g.autonomous_successes == 0 and g.raw_task_successes == 1
    assert failure_class(t) == "unverified_success"


def test_interrupted_qa_leaves_unverified(svc):
    s = make_session(svc, {"a": "success"})

    def interrupt(*_a):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        Runner(svc, lambda _s: FakeAdapter(), NoopController, qa_hook=interrupt).run_session(s.session_id)
    for t in svc.list_trials(s.session_id):
        assert not t.is_autonomous_success


def test_accepted_qa_counts(svc):
    s = make_session(svc, {"a": "success"})
    run(svc, s, FakeAdapter(), qa_hook=lambda t, d: QAReport(subject=t.trial_id))
    t = by_cond(svc, s)["a"]
    assert t.recording_quality == RecordingQuality.PASS and t.is_autonomous_success
    g = _verified(svc, s)
    assert g.evaluable == 1 and g.autonomous_successes == 1


def test_revalidation_clears_error_and_success_becomes_verified(svc):
    s = make_session(svc, {"a": "success"})
    run(svc, s, FakeAdapter(), qa_hook=_raising)
    t = by_cond(svc, s)["a"]
    rec = svc.set_recording_quality(t.trial_id, RecordingQuality.PASS, [])
    assert rec.is_autonomous_success and "qa_error" not in rec.evidence
    assert rec.evidence["qa_error_cleared_by"] == "pass"
    # and the same trial can be re-broken by a later crashed re-run
    rec2 = svc.set_recording_quality(
        t.trial_id, RecordingQuality.ERROR, [QACode.QA_EXECUTION_ERROR.value], qa_error="again"
    )
    assert not rec2.is_autonomous_success and rec2.evidence["qa_error"] == "again"


def test_paired_comparison_requires_accepted_qa(svc):
    from robotevalops.metrics.compare import compare_controllers

    s = make_session(svc, {"a": "success"}, controllers=2)
    run(svc, s, FakeAdapter(), qa_hook=_raising)
    cmp = compare_controllers(svc.list_trials(s.session_id), "ctrl0", "ctrl1")
    assert cmp.overall.pairs == 0
    assert {u.reason for u in cmp.unpaired} == {"not_evaluable_a"}


def test_unwritable_qa_report_fails_closed(svc, monkeypatch):
    import robotevalops.integration as integ

    s = make_session(svc, {"a": "success"})
    qa_hook, _ = integ.make_hooks(svc)

    def boom(*_a, **_k):
        raise PermissionError("read-only run dir")

    monkeypatch.setattr(integ, "atomic_write_text", boom)
    run(svc, s, FakeAdapter(), qa_hook=qa_hook)
    t = by_cond(svc, s)["a"]
    assert t.recording_quality == RecordingQuality.ERROR and not t.is_autonomous_success
    assert "PermissionError" in t.evidence["qa_error"]
