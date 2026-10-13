"""PyBullet Panda simulation tests (marked physics). Success must come from real physics."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("pybullet")

import cv2  # noqa: E402

from robotevalops.adapters.base import Action, Controller, Observation  # noqa: E402
from robotevalops.adapters.sim_pybullet import (  # noqa: E402
    BLOCK_NOMINAL_XY,
    CONTROL_HZ,
    HOME_JOINTS,
    TARGET_CENTER,
    TARGET_HALF,
    PyBulletPandaAdapter,
    corners_inside_square,
    footprint_fraction_in_square,
)
from robotevalops.controllers.base import (  # noqa: E402
    StopRequestedError,
    configs_dir,
    load_conditions,
    load_controller_specs,
)
from robotevalops.controllers.scripted_pick_place import ScriptedPickPlaceController  # noqa: E402
from robotevalops.schemas import Provenance, TerminationReason  # noqa: E402

pytestmark = pytest.mark.physics

CONDS = {c.name: c for c in load_conditions(configs_dir() / "conditions" / "sim_conditions.yaml")}
SPECS = {
    s.controller_id: s for s in load_controller_specs(configs_dir() / "controllers" / "sim_scripted.yaml")
}
A = SPECS["scripted_baseline_a"]


class HoldController(Controller):
    """No-op: holds the home joint pose with the gripper open. Never touches the block."""

    def __init__(self) -> None:
        self.spec = A

    def reset(self, observation: Observation, seed: int) -> None:
        pass

    def act(self, observation: Observation) -> Action:
        return Action([*HOME_JOINTS, 0.04, 20.0])


class NeverCloseController(ScriptedPickPlaceController):
    """Scripted pick-place whose gripper command is forced open at every step."""

    def act(self, observation: Observation) -> Action:
        a = super().act(observation)
        a.values[7] = 0.04
        return a


def new_adapter(render: bool = False) -> PyBulletPandaAdapter:
    return PyBulletPandaAdapter(render=render)


@pytest.fixture(scope="module")
def nominal_run(tmp_path_factory):
    """One full nominal run of controller A WITH rendering and recording."""
    out = tmp_path_factory.mktemp("nominal")
    a = new_adapter(render=True)
    a.reset(CONDS["nominal"], 1)
    ctl = ScriptedPickPlaceController(A)
    res = a.run_episode(ctl, out, 30.0, 2.0)
    a.close()
    return out, res, ctl


def test_preflight_and_metadata():
    a = new_adapter()
    pre = a.preflight()
    assert pre.ok, pre.failures()
    assert {c.name for c in pre.checks} >= {"pybullet_import", "panda_urdf", "render_tinyrenderer"}
    assert a.provenance == Provenance.SIMULATION and a.name == "pybullet_panda"
    a.close()


def test_panda_loads_and_block_starts_at_nominal_pose():
    a = new_adapter()
    obs = a.reset(CONDS["nominal"], 0)
    assert len(obs.state["joint_pos"]) == 7
    np.testing.assert_allclose(obs.state["joint_pos"], HOME_JOINTS, atol=0.02)
    bx, by, bz = obs.state["block_pos_world"]
    assert (bx, by) == pytest.approx(BLOCK_NOMINAL_XY, abs=1e-3) and bz == pytest.approx(0.02, abs=1e-3)
    assert obs.state["target_center_world"][:2] == list(TARGET_CENTER)
    a.close()


def test_geometry_helpers_hand_computed():
    ident = np.array([0.0, 0.0, 0.0, 1.0])
    c = TARGET_CENTER
    inside = np.array([c[0] + 0.03, c[1] - 0.03, 0.02])
    assert corners_inside_square(inside, ident, c, TARGET_HALF)  # corners at +/-0.05 <= 0.06
    edge = np.array([c[0] + 0.045, c[1], 0.02])  # corner at 0.065 > 0.06
    assert not corners_inside_square(edge, ident, c, TARGET_HALF)
    assert footprint_fraction_in_square(inside, ident, c, TARGET_HALF) == pytest.approx(1.0)
    half = np.array([c[0] + 0.06, c[1], 0.02])  # centre on the edge: half the footprint inside
    assert footprint_fraction_in_square(half, ident, c, TARGET_HALF) == pytest.approx(0.5, abs=0.06)
    assert footprint_fraction_in_square(np.array([0.0, 0.0, 0.02]), ident, c, TARGET_HALF) == 0.0


def test_noop_controller_leaves_block_at_start_and_fails(tmp_path):
    a = new_adapter()
    a.reset(CONDS["nominal"], 0)
    res = a.run_episode(HoldController(), tmp_path, 3.0, 2.0)
    ev = res.evidence
    a.close()
    assert res.termination_reason == TerminationReason.TIMEOUT and res.task_success is False
    start, final = np.array(ev["block_start_pos"]), np.array(ev["block_final_pos"])
    assert np.linalg.norm(final[:2] - start[:2]) < 1e-3
    assert ev["gripper_contact_steps"] == 0 and ev["in_target_fraction"] == 0.0
    assert ev["lift_m"] < 1e-3


def test_controller_that_never_closes_gripper_fails_without_moving_block(tmp_path):
    a = new_adapter()
    a.reset(CONDS["nominal"], 0)
    res = a.run_episode(NeverCloseController(A), tmp_path, 14.0, 2.0)
    ev = res.evidence
    a.close()
    assert res.task_success is False
    assert ev["both_finger_contact_steps"] == 0 and ev["lift_m"] < 0.01
    assert ev["block_displacement_m"] < 0.01
    assert ev["in_target_fraction"] == 0.0


def test_nominal_scripted_run_succeeds_from_real_physics(nominal_run):
    _, res, ctl = nominal_run
    ev = res.evidence
    assert res.termination_reason == TerminationReason.SUCCESS_CRITERION_MET and res.task_success is True
    assert res.error is None
    assert ev["lift_m"] > 0.05  # the block really left the table
    assert ev["both_finger_contact_steps"] > 10 and ev["max_contact_normal_force_n"] > 0.5
    assert ev["all_corners_inside"] is True and ev["in_target_fraction"] == pytest.approx(1.0)
    assert ev["released"] is True and ev["gripper_block_contact_points_final"] == 0
    assert ev["dwell_s"] >= 2.0 - 1e-6 and res.duration_s < 30.0
    assert [p for p, _ in ctl.phase_log][:6] == ["approach", "descend", "close", "lift", "transport", "lower"]
    fx, fy = ev["block_final_pos"][:2]
    assert abs(fx - TARGET_CENTER[0]) < TARGET_HALF - 0.02 and abs(fy - TARGET_CENTER[1]) < TARGET_HALF - 0.02
    assert ev["frames"].startswith("rendered simulator frames")


def test_recorder_files_and_measured_completeness(nominal_run):
    out, res, _ = nominal_run
    rec = res.recording
    assert (out / "video.mp4").stat().st_size > 1000 and (out / "trace.jsonl").exists()
    lines = (out / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    header, rows = json.loads(lines[0]), [json.loads(x) for x in lines[1:]]
    assert header["provenance"] == "simulation" and len(rows) == rec.trace_rows
    assert rec.frames_written == rec.frames_expected == len(rows) and rec.completeness == 1.0
    assert rec.video_kind == "rendered_simulator_frames" and rec.fps == CONTROL_HZ / 2
    cap = cv2.VideoCapture(str(out / "video.mp4"))
    n = 0
    while cap.read()[0]:
        n += 1
    cap.release()
    assert n == rec.frames_written  # decoded frames measured from the file itself
    ts = [r["t"] for r in rows]
    assert all(b > a for a, b in zip(ts, ts[1:], strict=False))
    assert len(rows[0]["state"]) == len(header["state_names"]) and len(rows[0]["action"]) == 9


def test_same_seed_reproducible_final_block_pose(tmp_path):
    finals = []
    for i in range(2):
        a = new_adapter()
        a.reset(CONDS["object_position"], 7)
        res = a.run_episode(ScriptedPickPlaceController(A), tmp_path / str(i), 30.0, 2.0)
        a.close()
        assert res.task_success is True
        finals.append(np.array(res.evidence["block_final_pos"]))
    assert np.max(np.abs(finals[0] - finals[1])) < 1e-3


def test_object_position_condition_changes_start_pose_within_bounds():
    starts = {}
    for name, seed in (("nominal", 3), ("object_position", 3), ("object_position", 4)):
        a = new_adapter()
        starts[(name, seed)] = np.array(a.reset(CONDS[name], seed).state["block_pos_world"])
        a.close()
    nom = starts[("nominal", 3)]
    p3, p4 = starts[("object_position", 3)], starts[("object_position", 4)]
    assert np.linalg.norm(p3[:2] - nom[:2]) > 1e-4 and np.linalg.norm(p3[:2] - p4[:2]) > 1e-4
    for p in (p3, p4):
        assert np.all(np.abs(p[:2] - np.array(BLOCK_NOMINAL_XY)) <= 0.04 + 2e-3)
    a = new_adapter()  # same seed -> same draw
    np.testing.assert_allclose(a.reset(CONDS["object_position"], 3).state["block_pos_world"], p3, atol=1e-6)
    a.close()


def test_object_position_condition_scripted_a_succeeds_on_several_seeds(tmp_path):
    for seed in (0, 1, 2):
        a = new_adapter()
        a.reset(CONDS["object_position"], seed)
        res = a.run_episode(ScriptedPickPlaceController(A), tmp_path / str(seed), 30.0, 2.0)
        a.close()
        assert res.task_success is True, (seed, res.evidence)


def test_visual_conditions_change_pixels_but_not_state_trajectory():
    traj, imgs = {}, {}
    for name in ("nominal", "lighting", "background", "occlusion"):
        a = new_adapter(render=True)
        obs = a.reset(CONDS[name], 5)
        ctl = ScriptedPickPlaceController(A)
        ctl.reset(obs, 5)
        states = []
        for _ in range(10):
            a.act(ctl.act(obs))
            obs = a.step().observation
            states.append(
                np.concatenate(
                    [obs.state["joint_pos"], obs.state["block_pos_world"], obs.state["ee_pos_world"]]
                )
            )
        imgs[name] = a.observe().image.astype(float)
        traj[name] = np.array(states)
        a.close()
    for name in ("lighting", "background", "occlusion"):
        np.testing.assert_array_equal(traj[name], traj["nominal"])  # state-based controller unaffected
        assert np.abs(imgs[name] - imgs["nominal"]).mean() > 1.0  # rendered frame really differs
    assert imgs["lighting"].mean() != pytest.approx(imgs["nominal"].mean(), abs=0.5)


def test_occlusion_only_alters_rendered_patch():
    a = new_adapter(render=True)
    a.reset(CONDS["occlusion"], 9)
    x0, y0, w, h = a._applied["occlusion_patch_xywh_px"]
    img = a.observe().image
    assert (img[y0 : y0 + h, x0 : x0 + w] == 128).all()
    assert 0.10 * 320 - 1 <= w <= 0.25 * 320 + 1
    a.close()


def test_timeout_is_failure_with_evidence(tmp_path):
    a = new_adapter()
    a.reset(CONDS["nominal"], 0)
    res = a.run_episode(ScriptedPickPlaceController(A), tmp_path, 2.0, 2.0)
    a.close()
    assert res.termination_reason == TerminationReason.TIMEOUT and res.task_success is False
    assert res.evidence["control_steps"] == 40 and res.evidence["dwell_s"] == 0.0


def test_stop_request_honoured_and_act_after_stop_raises(tmp_path):
    a = new_adapter()
    a.reset(CONDS["nominal"], 0)

    class Stopper(ScriptedPickPlaceController):
        n = 0

        def act(self, observation: Observation) -> Action:
            self.n += 1
            if self.n == 6:
                a.request_stop()
                a.request_stop()  # idempotent
            return super().act(observation)

    res = a.run_episode(Stopper(A), tmp_path, 30.0, 2.0)
    assert res.termination_reason == TerminationReason.SOFTWARE_STOP_REQUEST and res.task_success is None
    assert res.evidence["control_steps"] < 10
    with pytest.raises(StopRequestedError):
        a.act(Action([*HOME_JOINTS, 0.04, 20.0]))
    with pytest.raises(StopRequestedError):
        a.reset(CONDS["nominal"], 1)
    a.close()


def test_controller_error_becomes_infra_failure_with_text(tmp_path):
    class Boom(HoldController):
        def act(self, observation: Observation) -> Action:
            raise RuntimeError("synthetic simulator-side boom")

    a = new_adapter()
    a.reset(CONDS["nominal"], 0)
    res = a.run_episode(Boom(), tmp_path, 5.0, 2.0)
    a.close()
    assert res.termination_reason == TerminationReason.INFRA_FAILURE
    assert res.task_success is None and "synthetic simulator-side boom" in (res.error or "")


def test_nonfinite_action_is_rejected_as_infra_failure(tmp_path):
    class Nan(HoldController):
        def act(self, observation: Observation) -> Action:
            return Action([float("nan")] * 9)

    a = new_adapter()
    a.reset(CONDS["nominal"], 0)
    res = a.run_episode(Nan(), tmp_path, 5.0, 2.0)
    a.close()
    assert res.termination_reason == TerminationReason.INFRA_FAILURE and "finite" in (res.error or "")


def test_block_is_never_teleported(monkeypatch, tmp_path):
    import pybullet

    src = Path(__import__("robotevalops.adapters.sim_pybullet", fromlist=["x"]).__file__).read_text(
        encoding="utf-8"
    )
    assert "resetBasePositionAndOrientation" not in src
    assert "resetBaseVelocity" not in src

    def forbidden(*args, **kwargs):
        raise AssertionError("block/base teleport attempted")

    monkeypatch.setattr(pybullet, "resetBasePositionAndOrientation", forbidden)
    a = new_adapter()
    a.reset(CONDS["nominal"], 0)
    res = a.run_episode(HoldController(), tmp_path, 1.0, 2.0)
    a.close()
    assert res.termination_reason == TerminationReason.TIMEOUT


def test_registry_builds_sim_adapter_and_controller():
    from robotevalops.adapters.registry import get_adapter, get_controller

    a = get_adapter("pybullet_panda", None)
    assert isinstance(a, PyBulletPandaAdapter)
    a.close()
    c = get_controller(A, "pybullet_panda")
    assert isinstance(c, ScriptedPickPlaceController)
    c.close()


def test_controller_b_nominal_runs(tmp_path):
    a = new_adapter()
    a.reset(CONDS["nominal"], 0)
    res = a.run_episode(ScriptedPickPlaceController(SPECS["scripted_baseline_b"]), tmp_path, 30.0, 2.0)
    a.close()
    assert res.termination_reason in (TerminationReason.SUCCESS_CRITERION_MET, TerminationReason.TIMEOUT)
    assert res.evidence["lift_m"] > 0.05  # whatever the verdict, B really lifts the block


# ------------------------------------------------------- verification-round fixes (VF-01/02/15)


def test_success_evidence_records_grasp_and_empty_failed_criteria(nominal_run):
    _, res, _ = nominal_run
    ev = res.evidence
    assert ev["grasped"] is True and ev["bilateral_contact_ok"] and ev["lift_ok"]
    assert ev["both_finger_contact_steps"] >= 5 and ev["lift_m"] >= 0.03
    assert ev["failed_criteria"] == []


def test_noop_failure_lists_failed_criteria(tmp_path):
    a = new_adapter()
    a.reset(CONDS["nominal"], 0)
    res = a.run_episode(HoldController(), tmp_path, 2.0, 2.0)
    a.close()
    fc = " | ".join(res.evidence["failed_criteria"])
    assert res.evidence["grasped"] is False
    assert "grasp" in fc and "lift" in fc and "placement" in fc and "dwell" in fc


def test_placed_without_grasp_is_not_success(tmp_path):
    """Block teleported by the TEST (not product code) into the region, gripper open: dwell is met
    but there was no grasp/lift, so the episode must end TIMEOUT / failure with the reason recorded."""
    a = new_adapter()
    a.reset(CONDS["nominal"], 0)
    a.p.resetBasePositionAndOrientation(
        a._block, [TARGET_CENTER[0], TARGET_CENTER[1], 0.0202], [0, 0, 0, 1], physicsClientId=a._cid
    )
    res = a.run_episode(HoldController(), tmp_path, 5.0, 2.0)
    a.close()
    assert res.evidence["placement_dwell_met"] is True and res.evidence["all_corners_inside"] is True
    assert res.termination_reason == TerminationReason.TIMEOUT and res.task_success is False
    assert any(c.startswith("grasp") for c in res.evidence["failed_criteria"])


@pytest.mark.parametrize(
    "timeout,dwell", [(0.0, 2.0), (-1.0, 2.0), (5.0, 0.0), (5.0, -1.0), (float("nan"), 2.0)]
)
def test_nonpositive_timeout_or_dwell_refused(tmp_path, timeout, dwell):
    from robotevalops.errors import RobotEvalOpsError

    a = new_adapter()
    a.reset(CONDS["nominal"], 0)
    with pytest.raises(RobotEvalOpsError, match="> 0"):
        a.run_episode(HoldController(), tmp_path, timeout, dwell)
    a.close()


def test_strict_inclusion_boundary_touching_is_not_inside():
    c, q = TARGET_CENTER, np.array([0.0, 0.0, 0.0, 1.0])
    exactly = np.array([c[0], c[1] + TARGET_HALF - 0.02, 0.02])  # corner exactly on the boundary
    assert not corners_inside_square(exactly, q, c, TARGET_HALF)
    assert corners_inside_square(exactly - np.array([0, 1e-6, 0]), q, c, TARGET_HALF)


def test_tilted_block_overhanging_with_top_corners_is_not_inside():
    c = TARGET_CENTER
    th = np.radians(30.0)
    q = np.array([0.0, np.sin(th / 2), 0.0, np.cos(th / 2)])  # pitch 30 deg about y
    pos = np.array([c[0] + 0.035, c[1], 0.03])
    # hand computed: bottom corners span x in [0.0077, 0.0423], top corners reach x = 0.0623 > 0.06
    assert not corners_inside_square(pos, q, c, TARGET_HALF)
    assert corners_inside_square(pos - np.array([0.005, 0, 0]), q, c, TARGET_HALF)
