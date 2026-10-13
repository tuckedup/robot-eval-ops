"""Placeholder controller for hardware runs: actions come from LeRobot itself, not from Python."""

from __future__ import annotations

from robotevalops.adapters.base import Action, Controller, Observation
from robotevalops.errors import CapabilityUnavailableError
from robotevalops.schemas import ControllerSpec


class ExternalLeRobotController(Controller):
    """Carries the ControllerSpec (teleoperated leader arm, or a learned policy path) into the
    hardware adapter. It never produces actions itself: the lerobot subprocess does."""

    def __init__(self, spec: ControllerSpec) -> None:
        self.spec = spec

    def reset(self, observation: Observation, seed: int) -> None:
        return None

    def act(self, observation: Observation) -> Action:
        raise CapabilityUnavailableError(
            "actions are produced inside the lerobot subprocess (leader arm or --policy.path), "
            "not by this Python controller"
        )
