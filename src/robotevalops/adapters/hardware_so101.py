"""SO-101 hardware adapter (provenance PHYSICAL_HARDWARE) built on the LeRobot CLI wrapper.

Nothing here was verified against real hardware. Offline features work without lerobot or a robot:
the preflight reports each missing item as a failed check with an actionable message.

Motion-related methods (reset/act/step/run_episode) raise ``HardwareRefusedError`` unless the
adapter was constructed with ``hardware_mode=True``, an ``OperatorAcknowledgement`` for THIS
session, and ``preflight()`` has returned an all-ok result on this adapter instance.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

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
from robotevalops.adapters.lerobot_dataset import (
    EpisodeMeta,
    EpisodeTable,
    episode_to_trace,
    extract_episode_video,
    load_episode_table,
)
from robotevalops.adapters.lerobot_wrapper import (
    CameraSpec,
    HardwareGate,
    LeRobotWrapper,
    OperatorAcknowledgement,
    SO101Config,
    WrapperResult,
)
from robotevalops.controllers.base import StopRequestedError
from robotevalops.errors import CapabilityUnavailableError, HardwareRefusedError, RobotEvalOpsError
from robotevalops.schemas import (
    ConditionSpec,
    ControllerType,
    Provenance,
    RecordingSummary,
    TerminationReason,
)


def _count_decodable_frames(path: Path) -> int:
    """Decode the video with OpenCV and count frames actually readable (0 if undecodable)."""
    try:
        import cv2
    except ImportError:
        return 0
    cap = cv2.VideoCapture(str(path))
    n = 0
    try:
        while cap.isOpened() and cap.read()[0]:
            n += 1
    finally:
        cap.release()
    return n


PortLister = Callable[[], set[str]]
CameraProbe = Callable[[CameraSpec], tuple[bool, str]]


def default_port_lister() -> set[str]:
    """Enumerate serial ports without opening them. Raises CapabilityUnavailableError if impossible."""
    try:
        from serial.tools import list_ports
    except ImportError as e:
        raise CapabilityUnavailableError("pyserial is not installed; cannot enumerate serial ports") from e
    return {p.device for p in list_ports.comports()}


def default_camera_probe(cam: CameraSpec) -> tuple[bool, str]:
    """Open the camera device briefly (non-moving) and release it."""
    if cam.type == "intelrealsense":
        import importlib.util

        ok = importlib.util.find_spec("pyrealsense2") is not None
        return ok, "pyrealsense2 importable" if ok else "pyrealsense2 is not installed"
    try:
        import cv2
    except ImportError:
        return False, "opencv (cv2) is not installed"
    cap = cv2.VideoCapture(cam.index_or_path)
    try:
        opened = bool(cap.isOpened())
    finally:
        cap.release()
    return opened, "device opened" if opened else f"could not open camera {cam.index_or_path!r}"


class SO101HardwareAdapter(RobotAdapter):
    provenance = Provenance.PHYSICAL_HARDWARE
    name = "so101_lerobot"

    def __init__(
        self,
        config: SO101Config,
        *,
        session_id: str = "",
        hardware_mode: bool = False,
        acknowledgement: OperatorAcknowledgement | None = None,
        overrides: dict[str, list[str]] | None = None,
        port_lister: PortLister | None = None,
        camera_probe: CameraProbe | None = None,
    ) -> None:
        self.config = config
        self.session_id = session_id
        self.hardware_mode = bool(hardware_mode)
        self.acknowledgement = acknowledgement
        self.overrides = overrides
        self._port_lister = port_lister or default_port_lister
        self._camera_probe = camera_probe or default_camera_probe
        self.wrapper = LeRobotWrapper(config, overrides)
        self._stop = False
        self._preflight: PreflightResult | None = None
        self.last_result: WrapperResult | None = None

    # ------------------------------------------------------------------ gate
    def gate(self) -> HardwareGate:
        return HardwareGate(
            hardware_mode=self.hardware_mode,
            acknowledgement=self.acknowledgement,
            preflight_ok=self._preflight is not None and self._preflight.ok,
            session_id=self.session_id,
        )

    def _require_gate(self) -> None:
        self.gate().require()

    def check_motion_allowed(self) -> None:
        """Non-moving pre-trial check: raises HardwareRefusedError unless hardware mode, a
        this-session operator acknowledgement and a passing preflight (run on this instance) all hold."""
        self._require_gate()

    # ------------------------------------------------------------- preflight
    def preflight(self) -> PreflightResult:
        """NON-MOVING checks only; each missing item is a failed check with an actionable message."""
        c, w = self.config, self.wrapper
        checks: list[PreflightCheck] = [PreflightCheck("config_valid", True, "SO-101 config parsed")]
        info = w.info
        checks.append(
            PreflightCheck(
                "lerobot_installed",
                info.installed,
                f"lerobot {info.version}"
                if info.installed
                else "lerobot is not installed; install it per https://huggingface.co/docs/lerobot/so101 "
                "(uv sync --extra lerobot plus the feetech extra for motor support)",
            )
        )
        for tool in ("lerobot-teleoperate", "lerobot-record"):
            found = info.executables.get(tool)
            checks.append(
                PreflightCheck(
                    f"executable_{tool}",
                    found is not None,
                    " ".join(found)
                    if found
                    else f"{tool} not found on PATH or next to the Python interpreter",
                )
            )
        checks.append(
            PreflightCheck(
                "so101_follower_module",
                info.has_so_follower,
                "lerobot.robots.so_follower present"
                if info.has_so_follower
                else "lerobot.robots.so_follower not found; installed lerobot may lack so101_follower",
            )
        )
        checks.append(
            PreflightCheck(
                "so101_leader_module",
                info.has_so_leader,
                "lerobot.teleoperators.so_leader present"
                if info.has_so_leader
                else "lerobot.teleoperators.so_leader not found; installed lerobot may lack so101_leader",
            )
        )
        try:
            present = self._port_lister()
            err = None
        except CapabilityUnavailableError as e:
            present, err = set(), str(e)
        for role, port in (("follower", c.follower_port), ("leader", c.leader_port)):
            ok = port in present
            detail = (
                f"{port} present"
                if ok
                else (
                    err
                    or f"{port} not found among {sorted(present)}; plug in the {role} USB cable "
                    "and find the port with lerobot-find-port"
                )
            )
            checks.append(PreflightCheck(f"{role}_port_present", ok, detail))
        checks.extend(w.calibration_checks())
        if not c.cameras:
            checks.append(
                PreflightCheck(
                    "cameras_configured",
                    False,
                    "no cameras configured; video-backed operator scoring needs >=1 camera",
                )
            )
        for name, cam in c.cameras.items():
            try:
                ok, detail = self._camera_probe(cam)
            except Exception as e:  # noqa: BLE001
                ok, detail = False, f"camera probe failed: {type(e).__name__}: {e}"
            checks.append(PreflightCheck(f"camera_{name}_openable", ok, detail))
        self._preflight = PreflightResult(checks)
        return self._preflight

    # ---------------------------------------------------------------- motion
    def reset(self, condition: ConditionSpec, seed: int) -> Observation:
        """Hardware reset is the OPERATOR's physical scene reset; gated like any motion method."""
        self._require_gate()
        if self._stop:
            raise StopRequestedError("so101 adapter: stop requested; no further commands")
        return Observation(t=0.0, state={}, image=None)

    def observe(self) -> Observation:
        raise CapabilityUnavailableError(
            "per-step observation is not exposed; the SO-101 episode runs through lerobot-record "
            "inside run_episode()"
        )

    def act(self, action: Action) -> None:
        self._require_gate()
        if self._stop:
            raise StopRequestedError("so101 adapter: act() after request_stop() is refused")
        raise CapabilityUnavailableError(
            "per-step actions are not supported; use run_episode() (teleoperated record / supervised rollout)"
        )

    def step(self) -> StepResult:
        self._require_gate()
        raise CapabilityUnavailableError("per-step control is not supported; use run_episode()")

    def request_stop(self) -> None:
        """Idempotent SOFTWARE stop request. It prevents further commands and kills a running
        lerobot subprocess. It is NOT an emergency stop and has no latency guarantee; the real
        emergency stop is the facility's hardware procedure (power cut within operator reach)."""
        self._stop = True

    @property
    def stop_requested(self) -> bool:
        return self._stop

    def start_recording(self, out_dir: Path) -> None:
        raise CapabilityUnavailableError("recording is performed by lerobot-record inside run_episode()")

    def stop_recording(self) -> RecordingSummary:
        raise CapabilityUnavailableError("recording is performed by lerobot-record inside run_episode()")

    def close(self) -> None:
        return None

    def run_episode(
        self, controller: Controller, out_dir: Path, timeout_s: float, dwell_required_s: float
    ) -> EpisodeResult:
        """Delegate to the LeRobot wrapper. task_success is ALWAYS None (operator video scoring is
        required) and intervention is unknown."""
        self._require_gate()
        if self._stop:
            raise StopRequestedError("so101 adapter: run_episode() after request_stop() is refused")
        spec = controller.spec
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        ds_root = out_dir / "lerobot_dataset"
        cfg = self.config.model_copy(
            update={"dataset_root": str(ds_root), "episode_time_s": float(timeout_s), "num_episodes": 1}
        )
        wrapper = LeRobotWrapper(cfg, self.overrides)
        if spec.type == ControllerType.TELEOPERATED:
            plan = wrapper.build_record(num_episodes=1)
        elif spec.type == ControllerType.LEARNED:
            pol = spec.config.get("policy_path") or spec.artifact_relpath
            plan = wrapper.build_rollout(policy_path=str(pol) if pol else None, num_episodes=1)
        else:
            raise RobotEvalOpsError(
                "scripted controllers do not run on the SO-101 adapter; use teleoperated or learned"
            )
        res = wrapper.run(
            plan,
            gate=self.gate(),
            timeout_s=timeout_s + cfg.reset_time_s + 120.0,
            should_stop=lambda: self._stop,
        )
        self.last_result = res
        ev: dict[str, Any] = {
            "wrapper": res.as_dict(),
            "controller_type": spec.type.value,
            "intervention": "unknown",
            "scoring": "video-backed operator scoring required; task_success not judged by software",
            "provenance_note": "recorded via lerobot-record; no hardware verification claimed here",
        }
        reason, error = self._map(res)
        summary = RecordingSummary(video_kind="physical_camera")
        if res.ok:
            vids = sorted((ds_root / "videos").rglob("*.mp4")) if (ds_root / "videos").is_dir() else []
            table = self._episode_table(ds_root)
            if table is not None and table.episodes:
                # metadata-driven: ONE episode, ONE camera, only that episode's frames
                meta_ep = table.get(min(table.ids))
                assert meta_ep is not None
                cam = self._pick_camera(table, meta_ep)
                fps_v = float(self._read_fps(ds_root) or 0.0)
                ex: dict[str, Any] = (
                    extract_episode_video(ds_root, meta_ep, cam, out_dir / "video.mp4", fps_v)
                    if cam and fps_v
                    else {"ok": False, "frames": 0, "reason": "no camera feature or fps in dataset metadata"}
                )
                ev["video_extraction"] = ex
                if not ex["ok"]:
                    vids = []
                else:
                    ev["video_source"] = f"{ex['source']}[{ex['window'][0]}:{ex['window'][1]}] ({cam})"
                    tr = episode_to_trace(ds_root, out_dir / "trace.jsonl", episode=meta_ep.episode_index)
                    ev["trace_conversion"] = tr
                    decoded = int(ex["frames"])
            elif vids:
                shutil.copyfile(
                    vids[0], out_dir / "video.mp4"
                )  # legacy loose layout without episode metadata
                ev["video_source"] = str(vids[0])
                tr = episode_to_trace(ds_root, out_dir / "trace.jsonl")
                ev["trace_conversion"] = tr
                decoded = _count_decodable_frames(out_dir / "video.mp4")
            if vids:
                rows = int(tr["rows"]) if tr["ok"] else 0
                summary = RecordingSummary(
                    video_relpath="video.mp4",
                    trace_relpath="trace.jsonl" if tr["ok"] else None,
                    frames_expected=rows,
                    frames_written=decoded,
                    trace_rows=rows,
                    fps=float((self._read_fps(ds_root)) or 0.0),
                    completeness=float(min(1.0, decoded / rows)) if rows else 0.0,
                    video_kind="physical_camera",
                )
                ev["frame_counts"] = {
                    "decoded_video_frames": decoded,
                    "dataset_rows": rows,
                    "note": "completeness = decoded frames / dataset rows (measured); 0 if undecodable",
                }
                if not tr["ok"]:
                    ev["trace_absent_reason"] = tr["reason"]
            else:
                reason = TerminationReason.RECORDING_FAILURE
                why = (ev.get("video_extraction") or {}).get("reason")
                error = (
                    f"lerobot exited 0 but this episode's camera frames could not be extracted: {why}"
                    if why
                    else "lerobot exited 0 but no video (*.mp4) was found under the dataset videos/ directory"
                )
        return EpisodeResult(
            termination_reason=reason,
            duration_s=res.duration_s,
            task_success=None,
            evidence=ev,
            recording=summary,
            intervention_detected=False,
            error=error,
        )

    @staticmethod
    def _episode_table(ds_root: Path) -> EpisodeTable | None:
        try:
            info = json.loads((ds_root / "meta" / "info.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return load_episode_table(ds_root, info)

    def _pick_camera(self, table: EpisodeTable, ep: EpisodeMeta) -> str | None:
        """Configured camera whose key is `observation.images.<name>`, else the first camera key."""
        keys = sorted(ep.videos)
        for name in self.config.cameras:
            if f"observation.images.{name}" in keys:
                return f"observation.images.{name}"
        return keys[0] if keys else None

    @staticmethod
    def _read_fps(ds_root: Path) -> float | None:
        try:
            return float(json.loads((ds_root / "meta" / "info.json").read_text(encoding="utf-8"))["fps"])
        except (OSError, KeyError, ValueError, TypeError):
            return None

    @staticmethod
    def _map(res: WrapperResult) -> tuple[TerminationReason, str | None]:
        if res.status == "ok":
            # Episode window elapsed or operator ended early: outcome is unscored either way.
            return TerminationReason.TIMEOUT, None
        if res.status == "stopped":
            return TerminationReason.SOFTWARE_STOP_REQUEST, res.error
        return TerminationReason.INFRA_FAILURE, res.error or f"lerobot subprocess {res.status}"


__all__ = ["SO101HardwareAdapter", "HardwareRefusedError"]
