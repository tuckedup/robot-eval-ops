"""IK-based, state-based scripted pick-and-place controller for the PyBullet Panda simulation.

It reads simulator STATE (joint positions, end-effector pose, block pose, target region) - not
pixels - so it is not expected to react to visual-only conditions (lighting/background/occlusion).
A pass or fail here says nothing about learned-policy behaviour. A config is not a checkpoint.

State machine (each phase advances when the end effector is within tolerance of its waypoint):
  approach (above block) -> descend -> close (real contact: wait for the finger opening to settle at
  block width) -> lift -> transport (above target, compensating the measured block-in-hand offset)
  -> lower -> release (open and wait) -> retreat -> done.
If the close phase ends with the fingers fully closed (nothing between them) the controller opens
and stops in `failed_grasp`; there is no retry and no teleportation of anything.

Inverse kinematics: `p.calculateInverseKinematics` on a PRIVATE DIRECT-mode copy of the Panda that
is used purely as a kinematic solver (the controller never touches the simulation client).
Config keys (all in metres / seconds / newtons):
  hover_z, grasp_z, lift_z, place_clearance_z, move_speed, descend_speed, joint_speed_limit,
  grip_force, open_width_each, xy_tol, z_tol, close_settle_steps, release_settle_steps.
"""

from __future__ import annotations

import contextlib
import math
from typing import Any

import numpy as np

from robotevalops.adapters.base import Action, Controller, Observation
from robotevalops.schemas import ControllerSpec

CONTROL_HZ = 20
EE_LINK = 11
DEFAULTS: dict[str, float] = {
    "hover_z": 0.20,
    "grasp_z": 0.020,
    "lift_z": 0.22,
    "place_clearance_z": 0.004,
    "move_speed": 0.30,
    "descend_speed": 0.12,
    "joint_speed_limit": 1.2,
    "grip_force": 20.0,
    "open_width_each": 0.04,
    "xy_tol": 0.004,
    "z_tol": 0.004,
    "close_settle_steps": 8,
    "release_settle_steps": 8,
}
PHASES = (
    "approach",
    "descend",
    "close",
    "lift",
    "transport",
    "lower",
    "release",
    "retreat",
    "done",
    "failed_grasp",
)


class ScriptedPickPlaceController(Controller):
    def __init__(self, spec: ControllerSpec) -> None:
        self.spec = spec
        self.cfg: dict[str, Any] = {**DEFAULTS, **spec.config}
        self._cid: int | None = None
        self._panda = -1
        self.phase = "approach"
        self.phase_log: list[tuple[str, int]] = []
        self._k = 0

    # ---- private IK solver ------------------------------------------------
    def _ensure_solver(self) -> None:
        if self._cid is not None:
            return
        import pybullet as p

        from robotevalops.adapters.sim_pybullet import panda_urdf_path

        self._p = p
        self._cid = p.connect(p.DIRECT)
        self._panda = p.loadURDF(panda_urdf_path(), useFixedBase=True, physicsClientId=self._cid)
        lows, highs, ranges = [], [], []
        for j in range(7):
            info = p.getJointInfo(self._panda, j, physicsClientId=self._cid)
            lows.append(info[8])
            highs.append(info[9])
            ranges.append(info[9] - info[8])
        self._lows, self._highs, self._ranges = lows, highs, ranges

    def close(self) -> None:
        if self._cid is not None:
            self._p.disconnect(self._cid)
            self._cid = None

    def __del__(self) -> None:  # pragma: no cover - best effort cleanup
        with contextlib.suppress(Exception):
            self.close()

    def _ik(self, pos: np.ndarray, seed_q: list[float]) -> list[float]:
        p, cid = self._p, self._cid
        for j in range(7):
            p.resetJointState(self._panda, j, seed_q[j], physicsClientId=cid)
        sol = p.calculateInverseKinematics(
            self._panda,
            EE_LINK,
            [float(v) for v in pos],
            [float(v) for v in self._orn],
            lowerLimits=self._lows,
            upperLimits=self._highs,
            jointRanges=self._ranges,
            restPoses=list(seed_q),
            maxNumIterations=200,
            residualThreshold=1e-6,
            physicsClientId=cid,
        )
        return [float(v) for v in sol[:7]]

    # ---- Controller API ---------------------------------------------------
    def reset(self, observation: Observation, seed: int) -> None:
        self._ensure_solver()
        s = observation.state
        self._orn = np.array(s["ee_quat_world"])
        self._q_cmd = list(s["joint_pos"])
        self._goal_ee = np.array(s["ee_pos_world"])  # moving Cartesian setpoint
        self.phase = "approach"
        self.phase_log = [("approach", 0)]
        self._k = 0
        self._wait = 0
        self._prev_width = s["gripper_width"][0]
        self._hold_offset = np.zeros(2)
        self._finger = self.cfg["open_width_each"]

    def _enter(self, phase: str) -> None:
        self.phase = phase
        self.phase_log.append((phase, self._k))
        self._wait = 0

    def _move_toward(self, goal: np.ndarray, speed: float) -> bool:
        """Advance the Cartesian setpoint toward goal at `speed`; True when setpoint reached goal."""
        delta = goal - self._goal_ee
        dist = float(np.linalg.norm(delta))
        step = speed / CONTROL_HZ
        if dist <= step:
            self._goal_ee = goal.copy()
            return True
        self._goal_ee = self._goal_ee + delta / dist * step
        return False

    def _at(self, ee: np.ndarray, goal: np.ndarray) -> bool:
        c = self.cfg
        return bool(np.linalg.norm(ee[:2] - goal[:2]) <= c["xy_tol"] and abs(ee[2] - goal[2]) <= c["z_tol"])

    def act(self, observation: Observation) -> Action:
        c, s = self.cfg, observation.state
        ee = np.array(s["ee_pos_world"])
        blk = np.array(s["block_pos_world"])
        tgt = np.array(s["target_center_world"])
        width = s["gripper_width"][0]
        self._k += 1
        goal: np.ndarray | None = None
        speed = c["move_speed"]
        ph = self.phase

        if ph == "approach":
            goal = np.array([blk[0], blk[1], c["hover_z"]])
            reached = self._move_toward(goal, speed)
            if reached and self._at(ee, goal):
                self._enter("descend")
        elif ph == "descend":
            goal = np.array([blk[0], blk[1], c["grasp_z"]])
            reached = self._move_toward(goal, c["descend_speed"])
            if reached and self._at(ee, goal):
                self._enter("close")
        elif ph == "close":
            self._finger = 0.0
            goal = self._goal_ee
            self._wait += 1
            settled = abs(width - self._prev_width) < 1e-4
            if self._wait >= c["close_settle_steps"] and settled:
                if width < 0.02:  # fully closed with nothing between the fingers: missed grasp
                    self._enter("failed_grasp")
                else:
                    self._hold_offset = np.array(blk[:2] - ee[:2])
                    self._enter("lift")
        elif ph == "lift":
            goal = np.array([self._goal_ee[0], self._goal_ee[1], c["lift_z"]])
            reached = self._move_toward(goal, c["descend_speed"])
            if reached and abs(ee[2] - goal[2]) <= c["z_tol"] * 2:
                self._enter("transport")
        elif ph == "transport":
            goal = np.array([tgt[0] - self._hold_offset[0], tgt[1] - self._hold_offset[1], c["lift_z"]])
            reached = self._move_toward(goal, speed)
            if reached and self._at(ee, goal):
                self._enter("lower")
        elif ph == "lower":
            goal = np.array([self._goal_ee[0], self._goal_ee[1], c["grasp_z"] + c["place_clearance_z"]])
            reached = self._move_toward(goal, c["descend_speed"])
            if reached and self._at(ee, goal):
                self._enter("release")
        elif ph == "release":
            self._finger = c["open_width_each"]
            goal = self._goal_ee
            self._wait += 1
            if self._wait >= c["release_settle_steps"] and width >= 0.075:
                self._enter("retreat")
        elif ph == "retreat":
            self._finger = c["open_width_each"]
            goal = np.array([self._goal_ee[0], self._goal_ee[1], c["hover_z"]])
            reached = self._move_toward(goal, c["descend_speed"])
            if reached:
                self._enter("done")
        elif ph == "failed_grasp":
            self._finger = c["open_width_each"]
            goal = self._goal_ee
        else:  # done: hold position, gripper open
            self._finger = c["open_width_each"]
            goal = self._goal_ee
        self._prev_width = width

        q_ik = self._ik(self._goal_ee, self._q_cmd)
        lim = c["joint_speed_limit"] / CONTROL_HZ
        q_new = [qc + float(np.clip(qi - qc, -lim, lim)) for qc, qi in zip(self._q_cmd, q_ik, strict=True)]
        if not all(math.isfinite(v) for v in q_new):
            q_new = list(self._q_cmd)
        self._q_cmd = q_new
        force = c["grip_force"] if self._finger < 0.04 else 20.0
        return Action(
            values=[*q_new, float(self._finger), float(force)],
            names=[f"joint_target_{i}" for i in range(7)] + ["finger_target_m", "grip_force_n"],
        )
