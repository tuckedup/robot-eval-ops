"""Shared fixtures: tiny EvalConfig builders and a FakeAdapter whose behaviour is chosen per condition name."""  # noqa: E501

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from robotevalops.adapters.base import (
    Action,
    Controller,
    EpisodeResult,
    Observation,
    PreflightCheck,
    PreflightResult,
    RobotAdapter,
    StepResult,
)
from robotevalops.core.service import EvalService
from robotevalops.schemas import (
    ConditionSpec,
    ControllerSpec,
    ControllerType,
    EvalConfig,
    Provenance,
    RecordingSummary,
    TerminationReason,
)

VIDEO_BYTES = b"fake-video-bytes"
TRACE_BYTES = b'{"kind":"header"}\n'


def make_config(
    n_controllers: int = 2,
    n_conditions: int = 2,
    trials: int = 2,
    *,
    provenance: Provenance = Provenance.MOCK,
    backend: str | None = None,
    base_seed: int = 7,
    condition_names: list[str] | None = None,
) -> EvalConfig:
    names = condition_names or [f"cond{i}" for i in range(n_conditions)]
    return EvalConfig(
        name="cfg",
        provenance=provenance,
        backend=backend or ("mock" if provenance == Provenance.MOCK else "pybullet_panda"),
        controllers=[
            ControllerSpec(
                controller_id=f"ctrl{i}", type=ControllerType.SCRIPTED, version="1", config={"k": i}
            )
            for i in range(n_controllers)
        ],
        conditions=[ConditionSpec(name=n, kind="nominal") for n in names],
        trials_per_condition=trials,
        base_seed=base_seed,
    )


class NoopController(Controller):
    def __init__(self, spec: ControllerSpec) -> None:
        self.spec = spec

    def reset(self, observation: Observation, seed: int) -> None:
        return None

    def act(self, observation: Observation) -> Action:
        return Action(values=[0.0])


class FakeAdapter(RobotAdapter):
    """behaviors: condition name -> one of success|failure|infra_raise|abort|assisted|recording_failure|
    no_video|block_until_stop|reset_raise|safety_stop|hw_unjudged. Default 'success'."""

    def __init__(
        self,
        behaviors: dict[str, str] | None = None,
        provenance: Provenance = Provenance.MOCK,
        preflight_ok: bool = True,
    ) -> None:
        self.behaviors = behaviors or {}
        self.provenance = provenance
        self.name = "fake"
        self.preflight_ok = preflight_ok
        self.seeds: list[tuple[str, int]] = []
        self.episodes = 0
        self.closed = False
        self.stop_calls = 0
        self._stop = threading.Event()
        self.started = threading.Event()
        self._cond = ""

    def preflight(self) -> PreflightResult:
        return PreflightResult(
            [PreflightCheck("fake_check", self.preflight_ok, "" if self.preflight_ok else "broken")]
        )

    def reset(self, condition: ConditionSpec, seed: int) -> Observation:
        self._cond = condition.name
        self.seeds.append((condition.name, seed))
        if self.behaviors.get(condition.name) == "reset_refused":
            from robotevalops.errors import HardwareRefusedError

            raise HardwareRefusedError("hardware mode not enabled")
        if self.behaviors.get(condition.name) == "reset_raise":
            raise RuntimeError("reset boom")
        return Observation(t=0.0, state={})

    def observe(self) -> Observation:
        return Observation(t=0.0, state={})

    def act(self, action: Action) -> None:
        return None

    def step(self) -> StepResult:
        return StepResult(self.observe(), done=True)

    def request_stop(self) -> None:
        self.stop_calls += 1
        self._stop.set()

    @property
    def stop_requested(self) -> bool:
        return self._stop.is_set()

    def start_recording(self, out_dir: Path) -> None:
        return None

    def stop_recording(self) -> RecordingSummary:
        return RecordingSummary()

    def run_episode(
        self, controller: Controller, out_dir: Path, timeout_s: float, dwell_required_s: float
    ) -> EpisodeResult:
        self.episodes += 1
        b = self.behaviors.get(self._cond, "success")
        self.started.set()
        (out_dir / "trace.jsonl").write_bytes(TRACE_BYTES)
        video = "video.mp4"
        if b != "no_video":
            (out_dir / "video.mp4").write_bytes(VIDEO_BYTES)
        rec = RecordingSummary(video_relpath=video, trace_relpath="trace.jsonl", trace_rows=1)
        if b == "infra_raise":
            raise RuntimeError("camera exploded")
        if b == "block_until_stop":
            deadline = time.monotonic() + 10
            while not self._stop.is_set() and time.monotonic() < deadline:
                time.sleep(0.01)
            return EpisodeResult(TerminationReason.SOFTWARE_STOP_REQUEST, 0.2, None, {}, rec)
        if b == "abort":
            return EpisodeResult(TerminationReason.OPERATOR_ABORT, 0.2, None, {}, rec)
        if b == "safety_stop":
            return EpisodeResult(TerminationReason.SAFETY_STOP, 0.2, None, {}, rec)
        if b == "recording_failure":
            return EpisodeResult(TerminationReason.RECORDING_FAILURE, 0.2, True, {}, rec, error="disk full")
        if b == "failure":
            return EpisodeResult(TerminationReason.TIMEOUT, 30.0, False, {"in_target_fraction": 0.0}, rec)
        if b == "assisted":
            return EpisodeResult(
                TerminationReason.SUCCESS_CRITERION_MET, 3.0, True, {}, rec, intervention_detected=True
            )
        if b == "hw_unjudged":
            return EpisodeResult(TerminationReason.SUCCESS_CRITERION_MET, 3.0, None, {}, rec)
        return EpisodeResult(TerminationReason.SUCCESS_CRITERION_MET, 3.0, True, {"dwell_s": 2.0}, rec)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def svc(tmp_path: Path) -> EvalService:
    return EvalService(tmp_path / "home")


@pytest.fixture
def planned(svc: EvalService):
    """A mock session with 1 controller x 2 conditions x 1 trial = 2 planned trials."""
    cfg = make_config(1, 2, 1)
    s = svc.create_session("t", Provenance.MOCK, "mock", eval_config=cfg)
    trials = svc.plan_trials(s.session_id, cfg)
    return s, trials, cfg
