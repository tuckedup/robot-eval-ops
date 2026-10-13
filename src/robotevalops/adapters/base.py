"""Typed adapter + controller interfaces (lead-owned contract).

Physical-device adapters live in adapters/hardware_*.py and are kept separate from
adapters/mock.py and adapters/sim_*.py. Adapters never write to the database; the
Runner (core) owns lifecycle persistence and the single device lock.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from robotevalops.schemas import (
    ConditionSpec,
    ControllerSpec,
    Provenance,
    RecordingSummary,
    TerminationReason,
)


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class PreflightResult:
    checks: Sequence[PreflightCheck]

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)

    def failures(self) -> list[PreflightCheck]:
        return [c for c in self.checks if not c.ok]


@dataclass
class Observation:
    """State-like quantities are named exactly (e.g. 'joint_pos', 'block_pos_world').
    `image` is a rendered simulator frame for sim backends — NOT a physical camera frame."""

    t: float
    state: dict[str, list[float]]
    image: Any | None = None  # HxWx3 uint8 ndarray when available


@dataclass
class Action:
    values: list[float]
    names: list[str] = field(default_factory=list)


@dataclass
class StepResult:
    observation: Observation
    done: bool
    info: dict[str, Any] = field(default_factory=dict)


@dataclass
class EpisodeResult:
    """Outcome of one adapter-run episode. `task_success` is None when the adapter cannot
    judge (physical hardware => video-backed operator scoring is required)."""

    termination_reason: TerminationReason
    duration_s: float
    task_success: bool | None
    evidence: dict[str, Any]  # e.g. block_final_pos, in_target_fraction, released, dwell_s
    recording: RecordingSummary
    intervention_detected: bool = False
    error: str | None = None


class Controller(ABC):
    """Produces actions from observations. Deterministic given (spec, seed).
    LLM output must never be used as a Controller in the robot-motion loop."""

    spec: ControllerSpec

    @abstractmethod
    def reset(self, observation: Observation, seed: int) -> None: ...

    @abstractmethod
    def act(self, observation: Observation) -> Action: ...


class RobotAdapter(ABC):
    provenance: Provenance
    name: str

    @abstractmethod
    def preflight(self) -> PreflightResult:
        """Non-moving checks. Must never move hardware."""

    @abstractmethod
    def reset(self, condition: ConditionSpec, seed: int) -> Observation:
        """Reset the scene to the condition (sim) or confirm operator reset (hardware)."""

    @abstractmethod
    def observe(self) -> Observation: ...

    @abstractmethod
    def act(self, action: Action) -> None:
        """Apply an action. MUST raise if a stop was requested (no further commands)."""

    @abstractmethod
    def step(self) -> StepResult: ...

    @abstractmethod
    def request_stop(self) -> None:
        """Idempotent software stop request. After the first call no further commands are
        issued. This is NOT an emergency stop and carries no latency guarantee."""

    @property
    @abstractmethod
    def stop_requested(self) -> bool: ...

    @abstractmethod
    def start_recording(self, out_dir: Path) -> None: ...

    @abstractmethod
    def stop_recording(self) -> RecordingSummary: ...

    @abstractmethod
    def run_episode(
        self,
        controller: Controller,
        out_dir: Path,
        timeout_s: float,
        dwell_required_s: float,
    ) -> EpisodeResult:
        """Reset must already have been called. Records video+trace into out_dir
        (video.mp4, trace.jsonl) and returns evidence. Never fabricates success."""

    @abstractmethod
    def close(self) -> None: ...
