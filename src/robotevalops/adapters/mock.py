"""MockAdapter: seeded, deterministic, fast FIXTURE backend. Never robotics evidence.

Outcome rule (documented, deterministic, NOT physics):
    p = clamp(controller.config["skill"] (default 0.7) - condition.params["difficulty"] (default 0), 0, 1)
    u = SHA-256("mock-outcome-v1|seed|condition.name|controller.config_hash")[:8] / 2**64
    task_success = (u < p)
Same seed + condition + controller config => identical outcome and trace; a different seed
re-draws u. The synthetic trace/video are generated from the same seed. Every result carries
`evidence["fixture"] == "mock - not performance evidence"`.

Fault hooks (constructor `faults=`) produce REAL bad artifacts for QA tests:
  infra_exception, recording_failure, timeout, hang_until_stop, truncate_video,
  nonfinite_action, nonmonotonic_timestamps, drop_video.
"""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

import numpy as np

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
from robotevalops.controllers.base import StopRequestedError, unit_from_hash
from robotevalops.errors import RobotEvalOpsError
from robotevalops.recording.writers import TrialRecorder
from robotevalops.schemas import (
    ConditionSpec,
    Provenance,
    RecordingSummary,
    TerminationReason,
)

MOCK_LABEL = "mock — not performance evidence"
FAULTS = frozenset(
    {
        "infra_exception",
        "recording_failure",
        "timeout",
        "hang_until_stop",
        "truncate_video",
        "nonfinite_action",
        "nonmonotonic_timestamps",
        "drop_video",
    }
)
STATE_NAMES = ["mock_x", "mock_y", "mock_z", "mock_gripper"]
ACTION_NAMES = ["mock_dx", "mock_dy", "mock_dz", "mock_gripper"]


def mock_outcome(
    seed: int, condition: ConditionSpec, controller_config_hash: str, skill: float
) -> tuple[bool, float, float]:
    """Returns (success, u, p) per the documented rule."""
    difficulty = float(condition.params.get("difficulty", 0.0))
    p = min(1.0, max(0.0, skill - difficulty))
    u = unit_from_hash("mock-outcome-v1", seed, condition.name, controller_config_hash)
    return u < p, u, p


class MockAdapter(RobotAdapter):
    provenance = Provenance.MOCK
    name = "mock"

    def __init__(
        self,
        faults: set[str] | frozenset[str] | None = None,
        fps: float = 10.0,
        frame_size: tuple[int, int] = (64, 48),
        max_hang_s: float = 30.0,
    ) -> None:
        bad = set(faults or ()) - FAULTS
        if bad:
            raise RobotEvalOpsError(f"unknown mock fault(s) {sorted(bad)}; valid: {sorted(FAULTS)}")
        self.faults = frozenset(faults or ())
        self.fps = fps
        self.frame_size = frame_size
        self.max_hang_s = max_hang_s
        self._stop = False
        self._condition: ConditionSpec | None = None
        self._seed = 0
        self._k = 0
        self._recorder: TrialRecorder | None = None
        self._last_action: Action | None = None

    # --- RobotAdapter -------------------------------------------------------
    def preflight(self) -> PreflightResult:
        try:
            import imageio_ffmpeg

            imageio_ffmpeg.get_ffmpeg_exe()
            ok, detail = True, "ffmpeg available for tiny mock video"
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"imageio-ffmpeg unavailable: {e}"
        return PreflightResult(
            [
                PreflightCheck("mock_video_encoder", ok, detail),
                PreflightCheck("fixture_label", True, MOCK_LABEL),
            ]
        )

    def reset(self, condition: ConditionSpec, seed: int) -> Observation:
        if self._stop:
            raise StopRequestedError("mock adapter: stop was requested; create a new adapter")
        self._condition = condition
        self._seed = int(seed)
        self._k = 0
        return self.observe()

    def _state_at(self, k: int) -> list[float]:
        s = (self._seed % 1000) / 1000.0
        sign = 1 if s > 0.5 else -1
        return [0.5 + 0.1 * s + 0.002 * k, -0.15 + 0.01 * k * sign, 0.02 + 0.001 * k, 1.0 if k < 10 else 0.0]

    def observe(self) -> Observation:
        return Observation(
            t=self._k / self.fps, state={"mock_state": self._state_at(self._k)}, image=self._frame(self._k)
        )

    def _frame(self, k: int) -> np.ndarray:
        w, h = self.frame_size
        base = unit_from_hash("mock-frame", self._seed)
        img = np.zeros((h, w, 3), dtype=np.uint8)
        img[..., 0] = int(60 + 150 * base)
        img[..., 1] = np.linspace(0, 200, w, dtype=np.uint8)[None, :]
        img[..., 2] = (k * 7) % 256
        return img

    def act(self, action: Action) -> None:
        if self._stop:
            raise StopRequestedError("mock adapter: act() after request_stop() is refused")
        self._last_action = action

    def step(self) -> StepResult:
        if self._stop:
            raise StopRequestedError("mock adapter: step() after request_stop() is refused")
        self._k += 1
        return StepResult(self.observe(), done=False, info={"fixture": MOCK_LABEL})

    def request_stop(self) -> None:
        self._stop = True  # idempotent

    @property
    def stop_requested(self) -> bool:
        return self._stop

    def start_recording(self, out_dir: Path) -> None:
        self._recorder = TrialRecorder(
            out_dir,
            self.fps,
            STATE_NAMES,
            ACTION_NAMES,
            Provenance.MOCK,
            frame_size=self.frame_size,
            video_kind="mock_synthetic_frames",
        )

    def stop_recording(self) -> RecordingSummary:
        if self._recorder is None:
            raise RobotEvalOpsError("stop_recording() without start_recording()")
        rec, self._recorder = self._recorder, None
        return rec.close(expected_steps=self._k)

    def close(self) -> None:
        if self._recorder is not None:
            self._recorder.close()
            self._recorder = None

    # --- episode ------------------------------------------------------------
    def run_episode(
        self, controller: Controller, out_dir: Path, timeout_s: float, dwell_required_s: float
    ) -> EpisodeResult:
        if self._condition is None:
            raise RobotEvalOpsError("run_episode() requires reset() first")
        cond, seed, spec = self._condition, self._seed, controller.spec
        base_ev: dict[str, Any] = {
            "fixture": MOCK_LABEL,
            "faults_injected": sorted(self.faults),
            "condition": cond.name,
            "seed": seed,
            "controller_id": spec.controller_id,
            "controller_config_hash": spec.config_hash,
            "duration_is_synthetic": True,
        }
        if "infra_exception" in self.faults:
            raise RuntimeError("mock fault infra_exception: simulated adapter crash")
        out_dir = Path(out_dir)
        if "recording_failure" in self.faults:
            return EpisodeResult(
                TerminationReason.RECORDING_FAILURE,
                0.0,
                None,
                {**base_ev, "fault": "recording_failure"},
                RecordingSummary(video_kind="mock_synthetic_frames"),
                error="mock fault recording_failure: recorder could not be started",
            )
        skill = float(spec.config.get("skill", 0.7))
        success, u, p = mock_outcome(seed, cond, spec.config_hash, skill)
        n_steps = int(spec.config.get("steps", 30))
        if "timeout" in self.faults:
            n_steps, success = max(1, int(timeout_s * self.fps)), False
        self._k = 0
        controller.reset(self.observe(), seed)
        self.start_recording(out_dir)
        assert self._recorder is not None
        steps_done, stopped = 0, False
        hang = "hang_until_stop" in self.faults
        t_wall0 = time.monotonic()
        try:
            while True:
                if self._stop:
                    stopped = True
                    break
                if not hang and steps_done >= n_steps:
                    break
                if hang and time.monotonic() - t_wall0 > self.max_hang_s:
                    break
                obs = self.observe()
                act = controller.act(obs)
                vals = list(act.values)
                t = obs.t
                if "nonfinite_action" in self.faults and steps_done == 5:
                    vals[0] = math.nan
                if "nonmonotonic_timestamps" in self.faults and steps_done == 7:
                    t = obs.t - 0.5
                self._recorder.add(t, obs.image, obs.state["mock_state"], vals)
                self.act(act)
                self.step()
                steps_done += 1
                if hang:
                    time.sleep(0.02)
        finally:
            summary = self.stop_recording()
        duration = steps_done / self.fps
        if "truncate_video" in self.faults and (out_dir / "video.mp4").exists():
            data = (out_dir / "video.mp4").read_bytes()
            (out_dir / "video.mp4").write_bytes(data[: max(16, len(data) // 3)])
        if "drop_video" in self.faults:
            (out_dir / "video.mp4").unlink(missing_ok=True)
        ev = {**base_ev, "outcome_rule": "mock-outcome-v1", "u": u, "p": p, "steps": steps_done}
        if stopped:
            return EpisodeResult(TerminationReason.SOFTWARE_STOP_REQUEST, duration, None, ev, summary)
        if hang or "timeout" in self.faults:
            return EpisodeResult(TerminationReason.TIMEOUT, duration, False, ev, summary)
        if success:
            return EpisodeResult(TerminationReason.SUCCESS_CRITERION_MET, duration, True, ev, summary)
        return EpisodeResult(TerminationReason.TIMEOUT, duration, False, ev, summary)
