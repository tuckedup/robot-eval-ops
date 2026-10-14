"""Stress-study guard rails: seed separation, freeze enforcement, evidence-based failure categories."""

from __future__ import annotations

import shutil

import pytest
from eval_helpers import NONE, OK, PASS, TO, C, F, S, make_trial

from robotevalops.errors import RobotEvalOpsError
from robotevalops.schemas import TaskOutcome, TerminationReason
from robotevalops.study import stress

PROTO = "docs/stress-study/protocol_stress_v1.yaml"


def test_pilot_and_evaluation_seeds_are_disjoint_and_checked():
    proto = stress.load_protocol(PROTO)
    s = stress.seed_sets(proto)
    assert s["pilot"].isdisjoint(s["evaluation"]) and len(s["evaluation"]) == 29 * 8
    stress.check_seeds_disjoint(proto)
    clash = {**proto, "pilot": {**proto["pilot"], "base_seed": proto["evaluation"]["base_seed"]}}
    with pytest.raises(RobotEvalOpsError, match="overlap"):
        stress.check_seeds_disjoint(clash)


def test_every_condition_is_within_hard_bounds():
    from robotevalops.adapters.sim_pybullet import STRESS_BOUNDS

    for c in stress.load_eval_config_conditions(stress.load_protocol(PROTO)):
        assert c.kind == "physics_stress"
        for k, v in c.params.items():
            lo, hi = STRESS_BOUNDS[k]
            assert lo <= float(v) <= hi, (c.name, k, v)


def test_evaluation_refuses_without_freeze_and_after_change(tmp_path):
    p = tmp_path / "protocol_stress_v1.yaml"
    shutil.copy(PROTO, p)
    with pytest.raises(RobotEvalOpsError, match="not frozen"):
        stress.require_frozen(p)
    dig = stress.protocol_digest(p)
    stress.frozen_path(p).write_text(__import__("json").dumps(dig), encoding="utf-8")
    assert stress.require_frozen(p)["protocol_id"] == "stress_v1"
    p.write_text(p.read_text(encoding="utf-8") + "\n# edited after freezing\n", encoding="utf-8")
    with pytest.raises(RobotEvalOpsError, match="changed after freezing"):
        stress.require_frozen(p)


def test_freeze_needs_a_clean_pilot(tmp_path):
    p = tmp_path / "protocol_stress_v1.yaml"
    shutil.copy(PROTO, p)
    with pytest.raises(RobotEvalOpsError):
        stress.freeze(p, tmp_path / "empty_pilot_home")


def _fail(**ev):
    base = {
        "bilateral_contact_ok": True,
        "lift_ok": True,
        "all_corners_inside": True,
        "released": True,
        "target_center_xy": [0.5, 0.2],
        "block_final_pos": [0.5, 0.2, 0.02],
    }
    return make_trial(
        state=C,
        outcome=TaskOutcome.FAILURE,
        reason=TO,
        intervention=NONE,
        quality=PASS,
        evidence={**base, **ev},
    )


@pytest.mark.parametrize(
    ("ev", "cat"),
    [
        ({"bilateral_contact_ok": False}, "grasp_failed"),
        ({"lift_ok": False}, "lift_failed"),
        ({"all_corners_inside": False, "block_final_pos": [0.5, -0.1, 0.02]}, "dropped_in_transit"),
        ({"all_corners_inside": False, "block_final_pos": [0.5, 0.25, 0.02]}, "placement_outside_target"),
        ({"released": False}, "release_failed"),
        ({}, "dwell_not_held"),
    ],
)
def test_failure_categories_come_from_evidence(ev, cat):
    assert stress.categorize(_fail(**ev)) == cat


def test_success_and_infra_and_unverified():
    ok = make_trial(state=C, outcome=S, reason=OK, intervention=NONE, quality=PASS)
    assert stress.categorize(ok) is None
    assert stress.categorize(make_trial(state=F, reason=TerminationReason.INFRA_FAILURE)) == "infra_failure"
    unchecked = make_trial(state=C, outcome=S, reason=OK, intervention=NONE)
    assert stress.categorize(unchecked) == "unverified_recording"
