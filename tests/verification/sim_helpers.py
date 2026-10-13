# ruff: noqa: E501, B023
"""Adversarial controllers + harness for the PyBullet success-evidence audit (verifier-owned)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from robotevalops.adapters.base import Action, Controller, Observation
from robotevalops.adapters.sim_pybullet import HOME_JOINTS, TARGET_HALF, PyBulletPandaAdapter
from robotevalops.controllers.base import configs_dir, load_conditions, load_controller_specs
from robotevalops.controllers.scripted_pick_place import ScriptedPickPlaceController
from robotevalops.schemas import ConditionSpec

CONDS = {c.name: c for c in load_conditions(configs_dir() / "conditions" / "sim_conditions.yaml")}
SPEC_A = {
    s.controller_id: s for s in load_controller_specs(configs_dir() / "controllers" / "sim_scripted.yaml")
}["scripted_baseline_a"]


def run(
    controller: Controller,
    out_dir: Path,
    *,
    cond: str = "nominal",
    seed: int = 7,
    timeout_s: float = 30.0,
    dwell_s: float = 2.0,
    render: bool = False,
):
    ad = PyBulletPandaAdapter(render=render)
    try:
        ad.reset(CONDS[cond] if isinstance(cond, str) else cond, seed)
        return ad.run_episode(controller, out_dir, timeout_s, dwell_s)
    finally:
        ad.close()


class NoOp(Controller):
    def __init__(self) -> None:
        self.spec = SPEC_A

    def reset(self, observation: Observation, seed: int) -> None:
        pass

    def act(self, observation: Observation) -> Action:
        return Action([*HOME_JOINTS, 0.04, 20.0])


class _Scripted(ScriptedPickPlaceController):
    def __init__(self) -> None:
        super().__init__(SPEC_A)


class FreezeAfter(_Scripted):
    """Run the real scripted controller until `phase` is entered, then repeat the last arm command
    with a fixed finger command forever (closes gripper but never lifts when phase='lift')."""

    def __init__(self, phase: str, finger: float) -> None:
        super().__init__()
        self._freeze_phase, self._finger_cmd, self._frozen = phase, finger, None

    def act(self, observation: Observation) -> Action:
        if self._frozen is not None:
            return Action([*self._frozen, self._finger_cmd, 20.0])
        a = super().act(observation)
        if self.phase == self._freeze_phase:
            self._frozen = a.values[:7]
        return a


class HoldAboveNeverRelease(_Scripted):
    """Full pick+transport+lower, but the gripper never opens."""

    def act(self, observation: Observation) -> Action:
        a = super().act(observation)
        if self.phase in ("release", "retreat", "done"):
            a.values[7] = 0.0
            a.values[8] = 20.0
        return a


class ShiftedPlace(_Scripted):
    """Real pick-and-place but aims the placement `dy` metres off the target centre (straddle test)."""

    def __init__(self, dx: float, dy: float) -> None:
        super().__init__()
        self.dx, self.dy = dx, dy

    def act(self, observation: Observation) -> Action:
        st = dict(observation.state)
        t = list(st["target_center_world"])
        st["target_center_world"] = [t[0] + self.dx, t[1] + self.dy, t[2]]
        return super().act(Observation(t=observation.t, state=st, image=observation.image))


class Pusher(_Scripted):
    """Never closes the gripper. Positions behind the block (low y), sweeps +y through the target,
    then retreats up so 'released' is true. No grasp at any point."""

    def reset(self, observation: Observation, seed: int) -> None:
        super().reset(observation, seed)
        self.stage = "behind_hover"

    def act(self, observation: Observation) -> Action:
        c, s = self.cfg, observation.state
        ee = np.array(s["ee_pos_world"])
        blk = np.array(s["block_pos_world"])
        tgt = np.array(s["target_center_world"])
        self._k += 1
        self._finger = 0.04
        behind_y = blk[1] - 0.09
        push_end_y = tgt[1] + 0.02
        if self.stage == "behind_hover":
            g = np.array([blk[0], behind_y, 0.20])
            if self._move_toward(g, 0.3) and self._at(ee, g):
                self.stage = "behind_low"
        elif self.stage == "behind_low":
            g = np.array([blk[0], behind_y, 0.03])
            if self._move_toward(g, 0.1) and self._at(ee, g):
                self.stage = "push"
        elif self.stage == "push":
            g = np.array([self._goal_ee[0], push_end_y, 0.03])
            if self._move_toward(g, 0.06) and ee[1] > push_end_y - 0.01:
                self.stage = "up"
        else:
            g = np.array([self._goal_ee[0], self._goal_ee[1], 0.25])
            self._move_toward(g, 0.1)
        q_ik = self._ik(self._goal_ee, self._q_cmd)
        lim = c["joint_speed_limit"] / 20
        self._q_cmd = [
            qc + float(np.clip(qi - qc, -lim, lim)) for qc, qi in zip(self._q_cmd, q_ik, strict=True)
        ]
        return Action([*self._q_cmd, 0.04, 20.0])


__all__ = ["CONDS", "TARGET_HALF", "ConditionSpec", "run"]
