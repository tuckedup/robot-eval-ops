"""Backend registry used by Core: ``get_adapter(backend, session)`` and ``get_controller(spec, backend)``.

Backends: ``mock`` (fixture), ``pybullet_panda`` (simulation), ``so101_lerobot`` (physical hardware).
``lerobot_import`` is import-only (no adapter; see ``robotevalops robot import-dataset``).

Hardware sessions: the adapter reads its SO-101 YAML from ``$ROBOTEVALOPS_SO101_CONFIG`` (or
``configs/hardware/so101.yaml`` when present). ``hardware_mode`` is True ONLY when the environment
variable ``ROBOTEVALOPS_HARDWARE_MODE=1`` is set; the operator acknowledgement comes from the stored
session ack (``session.operator_ack_at``). Without these the adapter refuses motion.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

from robotevalops.adapters.base import Controller, RobotAdapter
from robotevalops.controllers.base import configs_dir
from robotevalops.errors import CapabilityUnavailableError
from robotevalops.schemas import ControllerSpec, ControllerType

BACKENDS = ("mock", "pybullet_panda", "so101_lerobot", "lerobot_import")


def _pybullet_available() -> tuple[bool, str]:
    if importlib.util.find_spec("pybullet") is None:
        return False, "pybullet is not installed (install the 'sim' extra: uv sync --extra sim)"
    if importlib.util.find_spec("pybullet_data") is None:
        return False, "pybullet_data is missing"
    return True, "pybullet importable"


def _lerobot_available() -> tuple[bool, str]:
    from robotevalops.adapters.lerobot_wrapper import discover_lerobot

    info = discover_lerobot()
    if not info.installed:
        return False, "lerobot is not installed (optional 'lerobot' extra)"
    return True, f"lerobot {info.version} installed (hardware still unverified; run hardware-check)"


def list_backends() -> list[dict[str, Any]]:
    """Availability of every backend (no hardware access, nothing is moved)."""
    ok_p, why_p = _pybullet_available()
    ok_l, why_l = _lerobot_available()
    return [
        {
            "backend": "mock",
            "provenance": "mock",
            "available": True,
            "detail": "seeded fixture backend; never performance evidence",
        },
        {"backend": "pybullet_panda", "provenance": "simulation", "available": ok_p, "detail": why_p},
        {
            "backend": "so101_lerobot",
            "provenance": "physical_hardware",
            "available": ok_l,
            "detail": why_l + "; motion also needs hardware mode, operator ack and passing preflight",
        },
        {
            "backend": "lerobot_import",
            "provenance": "imported_real_recording",
            "available": False,
            "detail": "import-only; no adapter. Use `robotevalops robot import-dataset`",
        },
    ]


def _so101_config_path() -> Path:
    env = os.environ.get("ROBOTEVALOPS_SO101_CONFIG")
    if env:
        return Path(env)
    return configs_dir() / "hardware" / "so101.yaml"


def get_adapter(backend: str, session: Any = None) -> RobotAdapter:
    if backend == "mock":
        from robotevalops.adapters.mock import MockAdapter

        return MockAdapter()
    if backend == "pybullet_panda":
        ok, why = _pybullet_available()
        if not ok:
            raise CapabilityUnavailableError(f"backend 'pybullet_panda' unavailable: {why}")
        from robotevalops.adapters.sim_pybullet import PyBulletPandaAdapter

        return PyBulletPandaAdapter()
    if backend == "so101_lerobot":
        from robotevalops.adapters.hardware_so101 import SO101HardwareAdapter
        from robotevalops.adapters.lerobot_wrapper import OperatorAcknowledgement, load_so101_config

        path = _so101_config_path()
        if not path.is_file():
            raise CapabilityUnavailableError(
                f"backend 'so101_lerobot' needs an SO-101 config at {path}; copy "
                "configs/hardware/so101.example.yaml and edit it (or set ROBOTEVALOPS_SO101_CONFIG)"
            )
        cfg = load_so101_config(path)
        sid = str(getattr(session, "session_id", "") or "")
        ack = None
        op = str(getattr(session, "operator", "") or "")
        ack_at = getattr(session, "operator_ack_at", None)
        if ack_at is not None and op:
            ack = OperatorAcknowledgement(operator=op, session_id=sid, acknowledged_at=ack_at)
        return SO101HardwareAdapter(
            cfg,
            session_id=sid,
            hardware_mode=os.environ.get("ROBOTEVALOPS_HARDWARE_MODE") == "1",
            acknowledgement=ack,
        )
    if backend == "lerobot_import":
        raise CapabilityUnavailableError(
            "backend 'lerobot_import' is import-only (no adapter); use `robotevalops robot import-dataset`"
        )
    raise CapabilityUnavailableError(f"unknown backend {backend!r}; known backends: {list(BACKENDS)}")


def get_controller(spec: ControllerSpec, backend: str) -> Controller:
    if backend == "mock":
        from robotevalops.controllers.mock_scripted import MockScriptedController

        return MockScriptedController(spec)
    if backend == "pybullet_panda":
        if spec.type == ControllerType.SCRIPTED:
            ok, why = _pybullet_available()
            if not ok:
                raise CapabilityUnavailableError(f"scripted controller needs pybullet: {why}")
            from robotevalops.controllers.scripted_pick_place import ScriptedPickPlaceController

            return ScriptedPickPlaceController(spec)
        raise CapabilityUnavailableError(
            f"no {spec.type.value} controller is implemented for pybullet_panda (only scripted); "
            "no trained policy checkpoint exists in this repository"
        )
    if backend == "so101_lerobot":
        if spec.type in (ControllerType.TELEOPERATED, ControllerType.LEARNED):
            from robotevalops.controllers.external import ExternalLeRobotController

            return ExternalLeRobotController(spec)
        raise CapabilityUnavailableError("scripted controllers do not run on the SO-101 backend")
    raise CapabilityUnavailableError(f"unknown backend {backend!r}; known backends: {list(BACKENDS)}")
