"""Audit A7: 'sustained bilateral contact' means CONSECUTIVE control steps.
Pure-logic test: the contact query is faked, no physics engine is started."""

from __future__ import annotations

import numpy as np
import pytest

from robotevalops.adapters import sim_pybullet as sp


def _adapter(pattern: list[bool], lift_z: float = 0.30):
    a = sp.PyBulletPandaAdapter.__new__(sp.PyBulletPandaAdapter)
    a._dwell = 0.0
    a._dwell_required = 2.0
    a._success = False
    a._target_half = sp.TARGET_HALF
    a._block_half = sp.BLOCK_HALF
    a._block_start = np.array([0.4, 0.0, 0.02])
    a._ev = {
        "gripper_contact_steps": 0,
        "both_finger_contact_steps": 0,
        "both_finger_contact_run": 0,
        "max_both_finger_contact_run": 0,
        "max_block_z_m": 0.02,
        "max_contact_normal_force_n": 0.0,
    }
    it = iter(pattern)
    a._contacts = lambda: (2, 2, 1.0) if next(it) else (0, 0, 0.0)
    a._block_pose = lambda: (np.array([0.4, 0.0, lift_z]), np.array([0.0, 0.0, 0.0, 1.0]))
    a._finger_width = lambda: 0.01
    return a


def _run(pattern, lift_z=0.30):
    a = _adapter(pattern, lift_z)
    for _ in pattern:
        a._update_task()
    return a._grasp_evidence(), a._ev


def test_interrupted_contact_is_not_a_sustained_grasp():
    ev, raw = _run([True, True, False, True, True, True, False, True, True])  # 7 total, longest run 3
    assert raw["both_finger_contact_steps"] == 7  # accumulated count would have passed the old rule (>=5)
    assert raw["max_both_finger_contact_run"] == 3
    assert ev["bilateral_contact_ok"] is False and ev["grasped"] is False
    assert ev["grasp_contact_rule"] == "consecutive_steps_v2"


def test_five_consecutive_steps_pass():
    ev, raw = _run([False, True, True, True, True, True, False])
    assert raw["max_both_finger_contact_run"] == 5
    assert ev["bilateral_contact_ok"] is True and ev["grasped"] is True


@pytest.mark.parametrize("run_len,ok", [(4, False), (5, True), (12, True)])
def test_threshold_is_five_consecutive_steps(run_len, ok):
    ev, _ = _run([True] * run_len)
    assert ev["bilateral_contact_ok"] is ok


def test_consecutive_contact_without_lift_is_still_not_grasped():
    ev, _ = _run([True] * 8, lift_z=0.02)
    assert ev["bilateral_contact_ok"] is True and ev["grasped"] is False
