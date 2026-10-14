"""Subprocess wrapper around the LeRobot command-line tools for the SO-101 (follower + leader).

Facts verified against the INSTALLED lerobot (0.4.4 when this file was written; see
docs/hardware-setup.md): console scripts lerobot-{calibrate,find-port,record,replay,teleoperate,
setup-motors,...} exist; robot/teleoperator types ``so101_follower`` / ``so101_leader`` are
registered by ``lerobot.robots.so_follower`` / ``lerobot.teleoperators.so_leader``; there is NO
``lerobot-rollout`` script. Learned-policy rollout is therefore built as ``lerobot-record`` with
``--policy.path`` (that option exists in ``lerobot_record.py``).

Safety design:
  * ARGUMENT LISTS only (``subprocess`` with ``shell=False``); operator-supplied strings are
    validated with strict regular expressions and never interpolated into a shell string.
  * ``lerobot-teleoperate``/``lerobot-record`` AUTO-START CALIBRATION when a calibration file is
    missing, which moves motors. This wrapper therefore refuses to launch unless the follower and
    leader calibration files already exist (joint calibration, made by an operator with
    ``lerobot-calibrate``).
  * Moving commands need a ``HardwareGate`` (explicit hardware mode + this-session operator
    acknowledgement + passing preflight). ``calibrate`` and ``replay`` builders are dry-run-only
    unless the gate passes AND an explicit confirm token is passed; nothing in the CLI executes
    them. Setup-motors/flash are not wrapped at all.
  * Failures (nonzero exit, timeout, missing executable) become structured results, never success.
  * A subprocess terminate/kill is a software stop. It is NOT an emergency stop.
Nothing in this module was verified against real hardware.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from robotevalops.adapters.base import PreflightCheck
from robotevalops.errors import (
    CapabilityUnavailableError,
    HardwareRefusedError,
    PreflightFailedError,
    RobotEvalOpsError,
)
from robotevalops.schemas import ControllerType, Provenance
from robotevalops.util import utcnow

LEROBOT_SOURCES = {
    "so101_docs": "https://huggingface.co/docs/lerobot/so101",
    "il_robots_docs": "https://huggingface.co/docs/lerobot/il_robots",
    "source": "https://github.com/huggingface/lerobot",
}
CONFIRM_TOKEN = "I_UNDERSTAND_THIS_MOVES_THE_ROBOT"
# Tools that connect() the arm and could auto-calibrate: launched via adapters/lerobot_guard.py
GUARDED_TOOLS = frozenset({"lerobot-record", "lerobot-teleoperate"})
# The argv builders and the calibration guard were checked ONLY against these installed lerobot versions (on
# Python 3.11, Windows). Other versions (uv.lock also resolves 0.6.1 for Python 3.12) are refused for motion.
TESTED_LEROBOT_VERSIONS = frozenset({"0.4.4"})

# --------------------------------------------------------------------------- validation

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
PORT_RE = re.compile(r"^(COM[0-9]{1,3}|/dev/[A-Za-z0-9_.:/-]{1,120})$")
REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}/[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
CAM_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
CAM_PATH_RE = re.compile(r"^[A-Za-z0-9_./:\\-]{1,200}$")
POLICY_RE = re.compile(r"^[A-Za-z0-9_./:\\-]{1,300}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _check(regex: re.Pattern[str], value: str, what: str) -> str:
    if not isinstance(value, str) or not regex.fullmatch(value) or ".." in value.split("/"):
        raise ValueError(f"invalid {what} {value!r}: must match {regex.pattern}")
    return value


class CameraSpec(BaseModel):
    """One OpenCV/RealSense camera as passed to LeRobot (--robot.cameras)."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["opencv", "intelrealsense"] = "opencv"
    index_or_path: int | str = 0
    width: int = Field(default=640, ge=16, le=7680)
    height: int = Field(default=480, ge=16, le=4320)
    fps: int = Field(default=30, ge=1, le=240)

    @field_validator("index_or_path")
    @classmethod
    def _v_path(cls, v: int | str) -> int | str:
        if isinstance(v, int):
            if v < 0:
                raise ValueError("camera index must be >= 0")
            return v
        return _check(CAM_PATH_RE, v, "camera index_or_path")


class SO101Config(BaseModel):
    """Operator configuration for one SO-101 follower + leader pair (see src/robotevalops/configs/hardware).

    JOINT calibration (motor ranges, made by ``lerobot-calibrate``) is referenced via the ids and
    optional calibration directories. CAMERA calibration (intrinsics/extrinsics) is separate and is
    only referenced informationally by ``camera_calibration_ref``; LeRobot does not consume it.
    """

    model_config = ConfigDict(extra="forbid")
    follower_id: str
    follower_port: str
    leader_id: str
    leader_port: str
    cameras: dict[str, CameraSpec] = Field(default_factory=dict)
    follower_calibration_dir: str | None = None
    leader_calibration_dir: str | None = None
    camera_calibration_ref: str | None = None
    dataset_repo_id: str = "local/so101_eval"
    dataset_root: str | None = None
    task: str = "Pick the block and place it inside the target region."
    num_episodes: int = Field(default=1, ge=1, le=1000)
    episode_time_s: float = Field(default=30.0, gt=0, le=3600)
    reset_time_s: float = Field(default=10.0, ge=0, le=3600)
    fps: int = Field(default=30, ge=1, le=240)
    display_data: bool = False
    policy_path: str | None = None
    device_id: str | None = None

    @field_validator("follower_id", "leader_id")
    @classmethod
    def _v_id(cls, v: str) -> str:
        return _check(ID_RE, v, "device id")

    @field_validator("follower_port", "leader_port")
    @classmethod
    def _v_port(cls, v: str) -> str:
        return _check(PORT_RE, v, "serial port")

    @field_validator("dataset_repo_id")
    @classmethod
    def _v_repo(cls, v: str) -> str:
        return _check(REPO_RE, v, "dataset repo_id")

    @field_validator("cameras")
    @classmethod
    def _v_cams(cls, v: dict[str, CameraSpec]) -> dict[str, CameraSpec]:
        for name in v:
            _check(CAM_NAME_RE, name, "camera name")
        return v

    @field_validator("task")
    @classmethod
    def _v_task(cls, v: str) -> str:
        if not v.strip() or len(v) > 200 or _CONTROL_RE.search(v):
            raise ValueError("task must be 1-200 printable characters without control characters")
        return v

    @field_validator("policy_path")
    @classmethod
    def _v_policy(cls, v: str | None) -> str | None:
        return None if v is None else _check(POLICY_RE, v, "policy path")

    @field_validator("dataset_root", "follower_calibration_dir", "leader_calibration_dir")
    @classmethod
    def _v_dir(cls, v: str | None) -> str | None:
        if v is not None and (_CONTROL_RE.search(v) or not v.strip() or len(v) > 400):
            raise ValueError("invalid path: empty, too long or contains control characters")
        return v


def load_so101_config(path: str | Path) -> SO101Config:
    import yaml

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RobotEvalOpsError(f"{path}: expected a YAML mapping")
    try:
        return SO101Config.model_validate(data)
    except ValueError as e:
        raise RobotEvalOpsError(f"{path}: invalid SO-101 config: {e}") from e


# --------------------------------------------------------------------------- gating


@dataclass(frozen=True)
class OperatorAcknowledgement:
    """Operator acknowledgement for ONE session (never reused across sessions)."""

    operator: str
    session_id: str
    acknowledged_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class HardwareGate:
    hardware_mode: bool
    acknowledgement: OperatorAcknowledgement | None
    preflight_ok: bool
    session_id: str = ""

    def refusal(self) -> str | None:
        if not self.hardware_mode:
            return "hardware mode was not explicitly enabled (--hardware-mode / hardware_mode=True)"
        a = self.acknowledgement
        if a is None or not a.operator.strip():
            return "no operator acknowledgement for this session (--ack-operator NAME)"
        if not self.session_id:
            return "adapter/gate session id is unset; an acknowledgement is bound to a specific session"
        if a.session_id != self.session_id:
            return "operator acknowledgement belongs to a different session"
        if not self.preflight_ok:
            return "preflight has not passed (run the non-moving hardware preflight and fix failures)"
        return None

    def require(self) -> None:
        r = self.refusal()
        if r:
            raise HardwareRefusedError(f"hardware motion refused: {r}")


# --------------------------------------------------------------------------- discovery

TOOLS = (
    "lerobot-teleoperate",
    "lerobot-record",
    "lerobot-replay",
    "lerobot-calibrate",
    "lerobot-find-port",
    "lerobot-find-cameras",
    "lerobot-setup-motors",
    "lerobot-train",
    "lerobot-eval",
    "lerobot-rollout",
)


@dataclass
class LeRobotInfo:
    version: str | None
    executables: dict[str, list[str] | None]  # argv prefix per tool, None if not found
    has_so_follower: bool
    has_so_leader: bool
    has_rollout_tool: bool
    package_dir: str | None
    sources: dict[str, str] = field(default_factory=lambda: dict(LEROBOT_SOURCES))

    @property
    def installed(self) -> bool:
        return self.version is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "installed": self.installed,
            "version": self.version,
            "package_dir": self.package_dir,
            "executables": self.executables,
            "robot_type_module_so_follower": self.has_so_follower,
            "teleoperator_module_so_leader": self.has_so_leader,
            "lerobot_rollout_tool_present": self.has_rollout_tool,
            "sources": self.sources,
        }


def discover_lerobot(overrides: dict[str, list[str]] | None = None) -> LeRobotInfo:
    """Find the installed lerobot without importing it (no torch import, no hardware access)."""
    overrides = overrides or {}
    try:
        version: str | None = metadata.version("lerobot")
    except metadata.PackageNotFoundError:
        version = None
    pkg_dir: str | None = None
    spec = importlib.util.find_spec("lerobot") if version or "lerobot" in sys.modules else None
    if spec is not None and spec.origin:
        pkg_dir = str(Path(spec.origin).parent)
    scripts = Path(sys.executable).parent
    exes: dict[str, list[str] | None] = {}
    for tool in TOOLS:
        if tool in overrides:
            exes[tool] = list(overrides[tool])
            continue
        found = shutil.which(tool)
        if found is None:
            for cand in (scripts / tool, scripts / f"{tool}.exe"):
                if cand.is_file():
                    found = str(cand)
                    break
        exes[tool] = [found] if found else None
    base = Path(pkg_dir) if pkg_dir else None
    return LeRobotInfo(
        version=version,
        executables=exes,
        has_so_follower=bool(base and (base / "robots" / "so_follower").is_dir()),
        has_so_leader=bool(base and (base / "teleoperators" / "so_leader").is_dir()),
        has_rollout_tool=exes.get("lerobot-rollout") is not None,
        package_dir=pkg_dir,
    )


def calibration_root() -> Path:
    """LeRobot's calibration root: $HF_LEROBOT_CALIBRATION or $HF_LEROBOT_HOME/calibration
    (default ~/.cache/huggingface/lerobot/calibration), as in lerobot.utils.constants."""
    explicit = os.environ.get("HF_LEROBOT_CALIBRATION")
    if explicit:
        return Path(explicit).expanduser()
    home = os.environ.get("HF_LEROBOT_HOME") or "~/.cache/huggingface/lerobot"
    return Path(home).expanduser() / "calibration"


def calibration_candidates(role: Literal["follower", "leader"], cfg: SO101Config) -> list[Path]:
    """Candidate JSON paths for a JOINT calibration file. LeRobot 0.4.4 stores it under
    <root>/{robots,teleoperators}/<class name attr 'so_follower'|'so_leader'>/<id>.json; the
    registered type names (so101_*) are also checked for other versions."""
    if role == "follower":
        ident, explicit, sub, names = (
            cfg.follower_id,
            cfg.follower_calibration_dir,
            "robots",
            (
                "so_follower",
                "so101_follower",
            ),
        )
    else:
        ident, explicit, sub, names = (
            cfg.leader_id,
            cfg.leader_calibration_dir,
            "teleoperators",
            (
                "so_leader",
                "so101_leader",
            ),
        )
    if explicit:
        return [Path(explicit).expanduser() / f"{ident}.json"]
    return [calibration_root() / sub / n / f"{ident}.json" for n in names]


SO101_MOTOR_IDS: dict[str, int] = {
    "shoulder_pan": 1,
    "shoulder_lift": 2,
    "elbow_flex": 3,
    "wrist_flex": 4,
    "wrist_roll": 5,
    "gripper": 6,
}
_CAL_FIELDS = ("id", "drive_mode", "homing_offset", "range_min", "range_max")


def validate_calibration_content(path: Path) -> list[str]:
    """Problems with a LeRobot joint-calibration JSON (``{motor: {id, drive_mode, homing_offset, range_min,
    range_max}}``), empty list if sound. An empty ``{}`` or a file missing any SO-101 motor is not one:
    LeRobot would treat it as uncalibrated and start motor calibration. This checks the FILE only; whether it
    matches the motors' stored values can only be known with the arm connected (see lerobot_guard)."""
    import json as _json

    try:
        data = _json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [f"unreadable calibration JSON: {e}"]
    if not isinstance(data, dict) or not data:
        return ["calibration file is empty (no motors); LeRobot would start motor calibration"]
    problems: list[str] = []
    for name in sorted(set(SO101_MOTOR_IDS) - set(data)):
        problems.append(f"motor {name!r} missing")
    for name in sorted(set(data) - set(SO101_MOTOR_IDS)):
        problems.append(f"unexpected motor {name!r} (SO-101 has {sorted(SO101_MOTOR_IDS)})")
    for name, want_id in SO101_MOTOR_IDS.items():
        rec = data.get(name)
        if rec is None:
            continue
        if not isinstance(rec, dict):
            problems.append(f"{name}: entry is not an object")
            continue
        bad = [f for f in _CAL_FIELDS if isinstance(rec.get(f), bool) or not isinstance(rec.get(f), int)]
        if bad:
            problems.append(f"{name}: missing/non-integer field(s) {bad}")
            continue
        if rec["id"] != want_id:
            problems.append(f"{name}: id {rec['id']} != expected {want_id}")
        if rec["drive_mode"] not in (0, 1):
            problems.append(f"{name}: drive_mode {rec['drive_mode']} not in (0, 1)")
        if not -2047 <= rec["homing_offset"] <= 2047:
            problems.append(f"{name}: homing_offset {rec['homing_offset']} outside +-2047")
        lo, hi = rec["range_min"], rec["range_max"]
        if not (0 <= lo < hi <= 4095):
            problems.append(f"{name}: range [{lo}, {hi}] is not 0 <= min < max <= 4095")
    return problems


# --------------------------------------------------------------------------- argv builders

CommandKind = Literal["teleoperate", "record", "rollout", "calibrate", "replay"]
MOVING_KINDS: frozenset[str] = frozenset({"teleoperate", "record", "rollout", "calibrate", "replay"})
DRY_RUN_ONLY_KINDS: frozenset[str] = frozenset({"calibrate", "replay"})


@dataclass
class CommandPlan:
    kind: CommandKind
    argv: list[str]
    controller_type: ControllerType | None
    provenance: Provenance = Provenance.PHYSICAL_HARDWARE
    dataset_path: str | None = None
    moves_robot: bool = True
    notes: list[str] = field(default_factory=list)


def _cameras_arg(cams: dict[str, CameraSpec]) -> str:
    parts = [
        f"{n}: {{type: {c.type}, index_or_path: {c.index_or_path}, width: {c.width}, "
        f"height: {c.height}, fps: {c.fps}}}"
        for n, c in cams.items()
    ]
    return "{ " + ", ".join(parts) + " }"


@dataclass
class WrapperResult:
    kind: str
    status: Literal["ok", "nonzero_exit", "timeout", "missing_executable", "stopped", "error"]
    returncode: int | None
    stdout_tail: str
    stderr_tail: str
    duration_s: float
    argv: list[str]
    tool_version: str | None
    dataset_path: str | None
    provenance: Provenance = Provenance.PHYSICAL_HARDWARE
    controller_type: ControllerType | None = None
    error: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None

    @property
    def ok(self) -> bool:
        """The PROCESS exited 0. This is not a task outcome (never a task success)."""
        return self.status == "ok"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "status": self.status,
            "returncode": self.returncode,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "duration_s": self.duration_s,
            "argv": self.argv,
            "tool_version": self.tool_version,
            "dataset_path": self.dataset_path,
            "provenance": self.provenance.value,
            "controller_type": self.controller_type.value if self.controller_type else None,
            "error": self.error,
            "task_success": None,
            "note": "process status only; task success requires operator video scoring",
        }


def _tail(text: str, max_lines: int = 40, max_chars: int = 4000) -> str:
    lines = text.splitlines()[-max_lines:]
    return "\n".join(lines)[-max_chars:]


class LeRobotWrapper:
    def __init__(self, config: SO101Config, overrides: dict[str, list[str]] | None = None) -> None:
        self.config = config
        self.overrides = overrides or {}
        self.info = discover_lerobot(self.overrides)

    # --- non-moving checks ---------------------------------------------------
    def calibration_checks(self) -> list[PreflightCheck]:
        out: list[PreflightCheck] = []
        for role in ("follower", "leader"):
            cands = calibration_candidates(role, self.config)
            hit = next((c for c in cands if c.is_file()), None)
            if hit:
                problems = validate_calibration_content(hit)
                if problems:
                    out.append(
                        PreflightCheck(
                            f"{role}_joint_calibration_file",
                            False,
                            f"{hit} is not a usable calibration: "
                            + "; ".join(problems)
                            + ". An operator must "
                            f"run lerobot-calibrate for the {role} by hand; this tool never calibrates.",
                        )
                    )
                else:
                    out.append(PreflightCheck(f"{role}_joint_calibration_file", True, str(hit)))
            else:
                out.append(
                    PreflightCheck(
                        f"{role}_joint_calibration_file",
                        False,
                        f"missing; looked for {[str(c) for c in cands]}. Run lerobot-calibrate for the "
                        f"{role} (id {getattr(self.config, role + '_id')}) yourself: lerobot-teleoperate/"
                        "record would otherwise start motor calibration automatically.",
                    )
                )
        return out

    def _exe(self, tool: str) -> list[str]:
        prefix = self.info.executables.get(tool)
        if prefix is None:
            raise CapabilityUnavailableError(
                f"{tool} not found (lerobot installed: {self.info.installed}); install lerobot with the "
                "feetech extra per https://huggingface.co/docs/lerobot/so101"
            )
        real_console_script = Path(prefix[0]).stem.lower().startswith("lerobot-")
        if tool in GUARDED_TOOLS and tool not in self.overrides and real_console_script:
            if self.info.version not in TESTED_LEROBOT_VERSIONS:
                raise CapabilityUnavailableError(
                    f"installed lerobot {self.info.version} is untested: command construction and the "
                    f"calibration guard were verified only against {sorted(TESTED_LEROBOT_VERSIONS)}; "
                    "refusing to build a "
                    "moving command (see docs/lerobot-datasets.md and docs/hardware-setup.md)"
                )
            # Real moving tools always start through the calibration guard (lerobot_guard.py). An explicit
            # override is a test/fake executable and is used as given.
            return [sys.executable, "-m", "robotevalops.adapters.lerobot_guard", tool]
        return list(prefix)

    # --- builders (dry-run capable; they never execute anything) -----------------
    def _robot_args(self, with_cameras: bool = True) -> list[str]:
        c = self.config
        args = [
            "--robot.type=so101_follower",
            f"--robot.port={c.follower_port}",
            f"--robot.id={c.follower_id}",
        ]
        if c.follower_calibration_dir:
            args.append(f"--robot.calibration_dir={c.follower_calibration_dir}")
        if with_cameras and c.cameras:
            args.append(f"--robot.cameras={_cameras_arg(c.cameras)}")
        return args

    def _teleop_args(self) -> list[str]:
        c = self.config
        args = [
            "--teleop.type=so101_leader",
            f"--teleop.port={c.leader_port}",
            f"--teleop.id={c.leader_id}",
        ]
        if c.leader_calibration_dir:
            args.append(f"--teleop.calibration_dir={c.leader_calibration_dir}")
        return args

    def _dataset_args(self, num_episodes: int | None = None) -> list[str]:
        c = self.config
        args = [
            f"--dataset.repo_id={c.dataset_repo_id}",
            f"--dataset.num_episodes={num_episodes or c.num_episodes}",
            f"--dataset.single_task={c.task}",
            f"--dataset.episode_time_s={c.episode_time_s:g}",
            f"--dataset.reset_time_s={c.reset_time_s:g}",
            f"--dataset.fps={c.fps}",
            "--dataset.push_to_hub=false",
        ]
        if c.dataset_root:
            args.append(f"--dataset.root={c.dataset_root}")
        return args

    def build_teleoperate(self) -> CommandPlan:
        argv = [
            *self._exe("lerobot-teleoperate"),
            *self._robot_args(),
            *self._teleop_args(),
            f"--display_data={'true' if self.config.display_data else 'false'}",
        ]
        return CommandPlan("teleoperate", argv, ControllerType.TELEOPERATED)

    def build_record(self, num_episodes: int | None = None) -> CommandPlan:
        argv = [
            *self._exe("lerobot-record"),
            *self._robot_args(),
            *self._teleop_args(),
            f"--display_data={'true' if self.config.display_data else 'false'}",
            *self._dataset_args(num_episodes),
        ]
        return CommandPlan("record", argv, ControllerType.TELEOPERATED, dataset_path=self._dataset_dir())

    def build_rollout(self, policy_path: str | None = None, num_episodes: int | None = None) -> CommandPlan:
        """Supervised learned-policy rollout = lerobot-record with --policy.path (no teleop leader).
        lerobot-rollout is NOT used: it is absent in 0.4.4 and its flags were not verified."""
        pol = policy_path or self.config.policy_path
        if not pol:
            raise RobotEvalOpsError("rollout needs a policy checkpoint path/repo (policy_path)")
        _check(POLICY_RE, pol, "policy path")
        argv = [
            *self._exe("lerobot-record"),
            *self._robot_args(),
            f"--display_data={'true' if self.config.display_data else 'false'}",
            *self._dataset_args(num_episodes),
            f"--policy.path={pol}",
        ]
        plan = CommandPlan("rollout", argv, ControllerType.LEARNED, dataset_path=self._dataset_dir())
        plan.notes.append("built on lerobot-record --policy.path; supervise the robot, e-stop within reach")
        return plan

    def build_calibrate(self, role: Literal["follower", "leader"] = "follower") -> CommandPlan:
        """Dry-run builder. Calibration moves/relaxes motors and needs a human; never automatic."""
        c = self.config
        if role == "follower":
            tail = [
                "--robot.type=so101_follower",
                f"--robot.port={c.follower_port}",
                f"--robot.id={c.follower_id}",
            ]
        else:
            tail = [
                "--teleop.type=so101_leader",
                f"--teleop.port={c.leader_port}",
                f"--teleop.id={c.leader_id}",
            ]
        plan = CommandPlan("calibrate", [*self._exe("lerobot-calibrate"), *tail], None)
        plan.notes.append("dry-run only: an operator runs lerobot-calibrate by hand")
        return plan

    def build_replay(self, episode: int = 0) -> CommandPlan:
        """Dry-run builder. Replay moves the arm autonomously; never automatic."""
        if not isinstance(episode, int) or episode < 0:
            raise ValueError("episode must be a non-negative int")
        c = self.config
        argv = [
            *self._exe("lerobot-replay"),
            *self._robot_args(with_cameras=False),
            f"--dataset.repo_id={c.dataset_repo_id}",
            f"--dataset.episode={episode}",
        ]
        if c.dataset_root:
            argv.append(f"--dataset.root={c.dataset_root}")
        plan = CommandPlan("replay", argv, None)
        plan.notes.append("dry-run only: replay moves the robot without teleoperation")
        return plan

    def _dataset_dir(self) -> str | None:
        c = self.config
        if c.dataset_root:
            return str(Path(c.dataset_root))
        hf = os.environ.get("HF_LEROBOT_HOME") or "~/.cache/huggingface/lerobot"
        return str(Path(hf).expanduser() / c.dataset_repo_id)

    # --- execution -------------------------------------------------------------
    def run(
        self,
        plan: CommandPlan,
        *,
        gate: HardwareGate | None,
        timeout_s: float,
        should_stop: Callable[[], bool] | None = None,
        confirm: str | None = None,
    ) -> WrapperResult:
        """Execute a plan. Refuses (raises) unless the gate passes and joint calibration exists.
        Subprocess problems are returned as structured results, never as success."""
        if plan.kind in MOVING_KINDS:
            if gate is None:
                raise HardwareRefusedError("hardware motion refused: no hardware gate supplied")
            gate.require()
        if plan.kind in DRY_RUN_ONLY_KINDS:
            if confirm != CONFIRM_TOKEN:
                raise HardwareRefusedError(
                    f"{plan.kind} is dry-run only; executing it needs hardware gate AND "
                    f"confirm={CONFIRM_TOKEN!r}, and is not exposed by the CLI"
                )
        else:
            missing = [c for c in self.calibration_checks() if not c.ok]
            if missing:
                raise PreflightFailedError(
                    "refusing to launch: joint calibration file(s) missing, LeRobot would start "
                    "motor calibration automatically. " + "; ".join(f"{m.name}: {m.detail}" for m in missing)
                )
        return execute_argv(
            plan.argv,
            kind=plan.kind,
            timeout_s=timeout_s,
            tool_version=self.info.version,
            controller_type=plan.controller_type,
            dataset_path=plan.dataset_path,
            should_stop=should_stop,
        )


def execute_argv(
    argv: Sequence[str],
    *,
    kind: str,
    timeout_s: float,
    tool_version: str | None = None,
    controller_type: ControllerType | None = None,
    dataset_path: str | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> WrapperResult:
    """Run an argument list (shell=False) and capture a structured result."""
    argv = [str(a) for a in argv]
    started = utcnow()
    t0 = time.monotonic()

    def _res(status: Any, rc: int | None, out: str, err: str, error: str | None = None) -> WrapperResult:
        ds = dataset_path if dataset_path and (Path(dataset_path) / "meta" / "info.json").is_file() else None
        return WrapperResult(
            kind=kind,
            status=status,
            returncode=rc,
            stdout_tail=_tail(out),
            stderr_tail=_tail(err),
            duration_s=time.monotonic() - t0,
            argv=argv,
            tool_version=tool_version,
            dataset_path=ds,
            controller_type=controller_type,
            error=error,
            started_at=started,
            ended_at=utcnow(),
        )

    try:
        proc = subprocess.Popen(  # noqa: S603 - argument list, shell=False, validated inputs
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            shell=False,
        )
    except FileNotFoundError as e:
        return _res("missing_executable", None, "", "", f"executable not found: {e}")
    except OSError as e:
        return _res("error", None, "", "", f"could not start process: {e}")
    out = err = ""
    status: str | None = None
    while True:
        try:
            out, err = proc.communicate(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            if should_stop is not None and should_stop():
                status = "stopped"
            elif time.monotonic() - t0 > timeout_s:
                status = "timeout"
            if status:
                proc.kill()  # software kill: NOT an emergency stop
                out, err = proc.communicate()
                break
    if status == "timeout":
        return _res("timeout", proc.returncode, out, err, f"timed out after {timeout_s:g}s; process killed")
    if status == "stopped":
        return _res("stopped", proc.returncode, out, err, "software stop requested; process killed")
    if proc.returncode != 0:
        if proc.returncode == 98 or "ROBOTEVALOPS_CALIBRATION_BLOCKED" in err:
            return _res(
                "nonzero_exit",
                proc.returncode,
                out,
                err,
                "calibration blocked: the motors' calibration does not match the calibration file; nothing "
                "was written to the motors. An operator must run lerobot-calibrate by hand.",
            )
        if proc.returncode == 97:
            return _res(
                "nonzero_exit",
                proc.returncode,
                out,
                err,
                "calibration guard could not be installed; the LeRobot tool was NOT started",
            )
        return _res("nonzero_exit", proc.returncode, out, err, f"exit code {proc.returncode}")
    return _res("ok", 0, out, err)
