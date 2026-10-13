"""Mock fixture controller: emits a deterministic action sequence. Not a robotics controller."""

from __future__ import annotations

import math

from robotevalops.adapters.base import Action, Controller, Observation
from robotevalops.schemas import ControllerSpec

MOCK_ACTION_NAMES = ["mock_dx", "mock_dy", "mock_dz", "mock_gripper"]


class MockScriptedController(Controller):
    """Deterministic function of (seed, step index). Fixture only."""

    def __init__(self, spec: ControllerSpec) -> None:
        self.spec = spec
        self._seed = 0
        self._k = 0

    def reset(self, observation: Observation, seed: int) -> None:
        self._seed = int(seed)
        self._k = 0

    def act(self, observation: Observation) -> Action:
        k = self._k
        self._k += 1
        phase = (self._seed % 97) / 97.0
        vals = [
            0.01 * math.sin(0.3 * k + phase),
            0.01 * math.cos(0.3 * k + phase),
            -0.005 if k < 15 else 0.005,
            1.0 if k < 10 or k > 20 else 0.0,
        ]
        return Action(values=vals, names=list(MOCK_ACTION_NAMES))
