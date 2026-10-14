"""Paired duration analysis: pairing, scenario collapse, statistics. Synthetic TrialRecords (not evidence)."""

from __future__ import annotations

import pytest
from eval_helpers import NONE, OK, PASS, C, S, make_trial

from robotevalops.analysis.paired_duration import analyze, paired_stat, render_markdown, sign_test_p


def _t(ctrl, cond, idx, dur, xy, session="s1", seed=None, **kw):
    ev = {
        "block_start_pos": [xy[0], xy[1], 0.02],
        "block_final_pos": [0.5, 0.2, 0.02],
        "target_center_xy": [0.5, 0.2],
        "max_contact_normal_force_n": 40.0 if ctrl == "A" else 24.0,
        "block_final_speed_mps": 1e-5,
        "max_block_height_m": 0.2,
    }
    return make_trial(
        controller_id=ctrl,
        condition=cond,
        trial_index=idx,
        state=C,
        outcome=S,
        reason=OK,
        intervention=NONE,
        quality=PASS,
        duration=dur,
        session_id=session,
        seed=seed or 100 + idx,
        evidence=ev,
        **kw,
    )


def _data():
    ts = []
    for i in range(4):  # four trials replay ONE scenario (deterministic nominal/visual conditions)
        ts += [
            _t("A", "nominal" if i < 2 else "lighting", i, 13.0, (0.5, -0.15)),
            _t("B", "nominal" if i < 2 else "lighting", i, 9.5, (0.5, -0.15)),
        ]
    for k in range(6):  # six distinct perturbed scenarios
        xy = (0.5 + 0.005 * (k + 1), -0.15 + 0.003 * (k + 1))
        ts += [
            _t("A", "object_position", 10 + k, 13.0 + 0.1 * k, xy),
            _t("B", "object_position", 10 + k, 9.6 + 0.1 * k, xy),
        ]
    return ts


def test_scenarios_collapse_and_inference_uses_distinct_scenarios():
    a = analyze(_data(), "A", "B")
    assert a.n_trial_pairs == 10 and a.n_scenarios == 7 and a.n_replayed_scenarios == 1
    assert a.duration.n_scenarios == 7
    assert a.duration.mean_diff_a_minus_b == pytest.approx((3.5 + 6 * 3.4) / 7)
    assert a.duration.n_a_greater == 7 and a.duration.sign_test_p_two_sided == pytest.approx(2 / 2**7)
    assert (
        a.duration.diff_interval.ci_low <= a.duration.mean_diff_a_minus_b <= a.duration.diff_interval.ci_high
    )
    # trial-weighted differs from scenario-weighted because it counts the replayed scenario 4 times
    tw = a.trial_weighted
    assert tw["n_trial_pairs"] == 10 and tw["mean_a_s"] != pytest.approx(a.duration.mean_a)
    assert next(r for r in a.scenario_table if r["trials_per_controller"] == 4)["replays_identical"]


def test_bootstrap_interval_is_reproducible():
    x = paired_stat("d", "s", [13, 13.2, 12.9, 13.4], [9.5, 9.7, 9.4, 9.9])
    y = paired_stat("d", "s", [13, 13.2, 12.9, 13.4], [9.5, 9.7, 9.4, 9.9])
    assert x.diff_interval == y.diff_interval and x.rel_interval == y.rel_interval
    assert x.relative_change_b_vs_a == pytest.approx((9.625 - 13.125) / 13.125)


def test_sign_test():
    assert sign_test_p(11, 0) == pytest.approx(2 / 2**11)
    assert sign_test_p(3, 3) == 1.0 and sign_test_p(0, 0) is None


def test_unpaired_and_cross_session_and_unverified_are_excluded_not_pooled():
    ts = _data() + [_t("A", "nominal", 99, 13.0, (0.5, -0.15), session="s2")]  # no B partner in s2
    ts.append(_t("B", "nominal", 77, 9.5, (0.5, -0.15), session="s1"))  # B without A
    a = analyze(ts, "A", "B")
    assert a.n_trial_pairs == 10
    assert any("missing partner" in u for u in a.unpaired) and len(a.unpaired) == 2


def test_unverified_qa_trials_never_enter_the_analysis():
    from robotevalops.schemas import RecordingQuality

    ts = _data()
    ts[0] = ts[0].model_copy(update={"recording_quality": RecordingQuality.UNCHECKED})
    a = analyze(ts, "A", "B")
    assert a.n_trial_pairs == 9 and any("not a verified" in u for u in a.unpaired)


def test_markdown_states_the_limits():
    md = render_markdown(analyze(_data(), "A", "B"))
    assert "SIMULATED" in md and "distinct start scenarios" in md and "Limits" in md
    assert "not robot throughput" in md.lower() or "not robot throughput" in md
