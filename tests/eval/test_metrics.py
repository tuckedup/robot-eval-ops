from __future__ import annotations

import json

import pytest
from eval_helpers import ASS, FL, NONE, OK, PASS, TO, C, F, S, known_scenario, make_trial

from robotevalops.metrics.compute import MOCK_BANNER, compute_group, compute_metrics
from robotevalops.metrics.failures import failure_report
from robotevalops.schemas import (
    ArtifactRef,
    ArtifactRole,
    ArtifactStatus,
    Provenance,
    TerminationReason,
)


def test_known_counts_exact():
    g = compute_group(known_scenario())
    assert (g.planned, g.attempted, g.completed, g.failed, g.aborted) == (20, 15, 10, 2, 3)
    assert g.not_attempted == 5
    assert g.unscored == 6  # 1 completed-unscored + 2 failed + 3 aborted (all attempted)
    assert g.evaluable == 8  # 4 autonomous + 2 assisted + 2 failures; quality-fail success excluded
    assert g.quality_excluded == 1
    assert g.autonomous_successes == 4
    assert g.assisted_successes == 2
    assert (g.success_per_attempt.k, g.success_per_attempt.n) == (4, 15)
    assert (g.success_per_evaluable.k, g.success_per_evaluable.n) == (4, 8)
    assert g.success_per_attempt.rate == pytest.approx(4 / 15)
    assert g.success_per_evaluable.rate == pytest.approx(0.5)
    assert (g.intervention_rate.k, g.intervention_rate.n) == (2, 15)
    # infra: 2 failed + interrupted_runner abort, all attempted
    assert (g.infra_abort_rate.k, g.infra_abort_rate.n) == (3, 15)
    assert (g.recording_pass_rate.k, g.recording_pass_rate.n) == (6, 15)
    assert g.duration.n == 11
    assert g.duration.mean == pytest.approx(141.2 / 11)
    assert (g.duration.median, g.duration.min, g.duration.max) == (12.0, 0.2, 30.0)
    assert g.duration.p95 is None  # n < 20: not reported
    assert g.reset_duration.n == 0 and g.reset_duration.mean is None
    assert any("small n" in w for w in g.warnings)


def test_assisted_success_not_autonomous_and_infra_stays_in_denominator():
    ts = [
        make_trial(state=C, outcome=S, reason=OK, intervention=NONE, quality=PASS),
        make_trial(state=C, outcome=S, reason=OK, intervention=NONE, quality=PASS),
        make_trial(state=C, outcome=S, reason=OK, intervention=ASS),
        make_trial(state=F, reason=TerminationReason.INFRA_FAILURE),
    ]
    g = compute_group(ts)
    assert g.autonomous_successes == 2
    assert g.attempted == 4  # infra failure remains in the attempted denominator
    assert g.success_per_attempt.rate == 0.5
    assert g.evaluable == 3 and g.success_per_evaluable.rate == pytest.approx(2 / 3)


def test_planned_never_attempted_stays_and_n_zero_safe():
    g = compute_group([make_trial(), make_trial()])
    assert g.planned == 2 and g.attempted == 0
    assert g.success_per_attempt.rate is None and g.success_per_attempt.ci_low is None
    assert g.success_per_evaluable.rate is None
    assert any("never attempted" in w for w in g.warnings)
    empty = compute_group([])
    assert empty.planned == 0 and empty.duration.mean is None
    assert any("no trials" in w for w in empty.warnings)
    rep = compute_metrics([])
    assert rep.banner is None and rep.overall.planned == 0


def test_wilson_attached_to_rates():
    ts = [make_trial(state=C, outcome=S, reason=OK, intervention=NONE, quality=PASS) for _ in range(8)]
    ts += [make_trial(state=C, outcome=FL, reason=TO, intervention=NONE) for _ in range(2)]
    r = compute_group(ts).success_per_attempt
    assert (r.k, r.n) == (8, 10)
    assert r.ci_low == pytest.approx(0.4902, abs=1e-4)
    assert r.ci_high == pytest.approx(0.9433, abs=1e-4)


def test_mock_banner_and_breakdowns_carry_provenance_and_controller_type():
    rep = compute_metrics(known_scenario(Provenance.MOCK))
    assert rep.banner == MOCK_BANNER
    for grp in [rep.overall, *rep.by_condition, *rep.by_controller, *rep.by_controller_condition]:
        assert grp.provenances == ["mock"] and grp.controller_types == ["scripted"]
    assert rep.by_controller[0].key["controller_type"] == "scripted"
    assert rep.by_controller[0].key["provenance"] == "mock"
    assert compute_metrics(known_scenario()).banner is None
    json.dumps(rep.model_dump(mode="json"))  # JSON-serialisable


def test_breakdown_sums():
    ts = known_scenario(controller_id="A", condition="c0") + known_scenario(controller_id="B", condition="c1")
    rep = compute_metrics(ts)
    assert sum(g.planned for g in rep.by_controller) == 40
    assert sum(g.planned for g in rep.by_condition) == 40
    assert len(rep.by_controller_condition) == 2
    assert {g.key["condition"] for g in rep.by_condition} == {"c0", "c1"}


def _art(role, rel, status, sha="a" * 64):
    return ArtifactRef(role=role, relpath=rel, sha256=sha, status=status)


def test_artifact_completeness_and_checksum_counts():
    v, t = ArtifactRole.VIDEO, ArtifactRole.TRACE
    st = ArtifactStatus
    t1 = make_trial(
        state=C,
        outcome=S,
        reason=OK,
        intervention=NONE,
        artifacts=[_art(v, "v1", st.VERIFIED), _art(t, "t1", st.UPLOADED)],
    )
    t2 = make_trial(
        state=C,
        outcome=S,
        reason=OK,
        intervention=NONE,
        artifacts=[_art(v, "v2", st.MISMATCH), _art(t, "t2", st.PRESENT)],
    )
    t3 = make_trial(
        state=F, reason=TerminationReason.INFRA_FAILURE, artifacts=[_art(v, "v3", st.MISSING, sha=None)]
    )
    a = compute_group([t1, t2, t3, make_trial()]).artifacts  # the planned trial contributes nothing
    assert a.expected == 6  # t1:2, t2:2, t3: 1 registered + 1 unregistered trace
    assert a.present_with_hash == 3  # verified, uploaded, present
    assert a.missing == 2  # t3 video missing + t3 trace never registered
    assert (a.checksum_verified, a.checksum_mismatch, a.checksum_unverified) == (1, 1, 2)
    assert (a.checksum_agreement.k, a.checksum_agreement.n) == (
        1,
        3,
    )  # verified / (uploaded+verified+mismatch)
    assert a.completeness.rate == pytest.approx(0.5)


def test_failure_report_never_drops_rows():
    ts = known_scenario()
    ts[0] = ts[0].model_copy(update={"qa_flags": ["missing_video"]})
    rep = failure_report(ts)
    assert sum(r.count for r in rep.rows) == 20 == rep.total_trials
    assert rep.class_totals == {
        "aborted_infra": 1,
        "aborted_operator_or_stop": 2,
        "autonomous_success": 4,
        "completed_unscored": 1,
        "infra_failure": 2,
        "non_autonomous_success": 3,
        "not_attempted": 5,
        "task_failure": 2,
    }
    assert rep.qa_flag_counts == {"missing_video": 1}


def test_unchecked_recordings_are_counted_and_warned():
    from robotevalops.schemas import RecordingQuality

    ts = [
        make_trial(state=C, outcome=S, reason=OK, intervention=NONE, quality=PASS),
        make_trial(state=C, outcome=S, reason=OK, intervention=NONE, quality=RecordingQuality.UNCHECKED),
        make_trial(state=C, outcome=FL, reason=TO, intervention=NONE, quality=RecordingQuality.UNCHECKED),
        make_trial(),  # never attempted: not counted as unchecked
    ]
    g = compute_group(ts)
    assert g.recording_unchecked == 2
    assert (g.recording_pass_rate.k, g.recording_pass_rate.n) == (1, 3)  # unchecked lowers the pass rate
    assert any(
        "2 attempted trial(s) have no recording QA result; run 'robotevalops data validate' "
        "(or session run, which now runs QA) before trusting evaluable counts" in w
        for w in g.warnings
    )
    clean = compute_group([make_trial(state=C, outcome=S, reason=OK, intervention=NONE, quality=PASS)])
    assert clean.recording_unchecked == 0
    assert not any("no recording QA result" in w for w in clean.warnings)
