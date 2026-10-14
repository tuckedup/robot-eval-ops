"""Launch a LeRobot moving tool with automatic calibration / motor setup structurally disabled.

Why this exists (audit A4): ``lerobot-record`` / ``lerobot-teleoperate`` call ``robot.connect()`` with
``calibrate=True``. If the calibration stored in the motors does not match the file, ``connect`` calls
``calibrate()``, which (for an empty calibration) disables torque and writes ``Operating_Mode`` to every motor
BEFORE it asks the operator anything, and (for a non-empty one) asks on stdin whether to overwrite the motors
with the file. Neither may ever happen inside a supervised run. LeRobot 0.4.4 has no flag to forbid it,
so this launcher replaces ``calibrate`` / ``setup_motors`` on the SO-101 classes with a function that raises,
then runs the real tool unchanged. A calibration mismatch therefore aborts the run with an explicit
message instead of touching a motor.

Fail closed: if lerobot cannot be imported, a target class is missing, or the replacement did not take effect,
the process exits non-zero and the real tool is NOT started.

Usage (what the wrapper emits):  python -m robotevalops.adapters.lerobot_guard <lerobot-tool> [tool args...]
"""

from __future__ import annotations

import importlib
import sys
from typing import Any

BLOCK_MARKER = "ROBOTEVALOPS_CALIBRATION_BLOCKED"
EXIT_GUARD_FAILED = 97
EXIT_CALIBRATION_BLOCKED = 98

# tool -> (module, entry function)
TOOL_ENTRYPOINTS: dict[str, tuple[str, str]] = {
    "lerobot-record": ("lerobot.scripts.lerobot_record", "main"),
    "lerobot-teleoperate": ("lerobot.scripts.lerobot_teleoperate", "main"),
}
# (module, class) pairs whose automatic calibration / setup must be unreachable
GUARDED_CLASSES: tuple[tuple[str, str], ...] = (
    ("lerobot.robots.so_follower.so_follower", "SOFollower"),
    ("lerobot.teleoperators.so_leader.so_leader", "SOLeader"),
)
GUARDED_METHODS = ("calibrate", "setup_motors")


class CalibrationBlockedError(RuntimeError):
    """Raised instead of running LeRobot's calibration / motor-setup routine."""


def _blocked(name: str) -> Any:
    def refuse(self: Any, *_a: Any, **_k: Any) -> None:
        raise CalibrationBlockedError(
            f"{BLOCK_MARKER}: {type(self).__name__}.{name}() was about to run. The motors' calibration does "
            "not match the calibration file (or no file exists). RobotEvalOps never calibrates or sets up "
            "motors inside a supervised run: nothing was written to the motors. A trained operator must run "
            "`lerobot-calibrate` by hand, then retry."
        )

    refuse._roe_blocked = True  # type: ignore[attr-defined]
    return refuse


def install_calibration_guard(
    classes: tuple[tuple[str, str], ...] = GUARDED_CLASSES,
) -> list[str]:
    """Replace the guarded methods; return the dotted names patched. Raises if any target is missing or the
    replacement is not in effect afterwards (fail closed)."""
    patched: list[str] = []
    for module_name, class_name in classes:
        module = importlib.import_module(module_name)
        cls = getattr(module, class_name, None)
        if cls is None:
            raise RuntimeError(f"guard cannot find {module_name}.{class_name}; refusing to launch unguarded")
        for method in GUARDED_METHODS:
            if not hasattr(cls, method):
                continue
            setattr(cls, method, _blocked(method))
            if not getattr(getattr(cls, method), "_roe_blocked", False):
                raise RuntimeError(f"guard did not take effect on {class_name}.{method}")
            patched.append(f"{class_name}.{method}")
        if not any(p.startswith(class_name + ".calibrate") for p in patched):
            raise RuntimeError(f"{class_name} has no calibrate(); guard cannot verify it is blocked")
    return patched


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in TOOL_ENTRYPOINTS:
        print(f"guard: tool must be one of {sorted(TOOL_ENTRYPOINTS)}; got {args[:1]}", file=sys.stderr)
        return EXIT_GUARD_FAILED
    tool, tool_args = args[0], args[1:]
    try:
        patched = install_calibration_guard()
        module_name, fn_name = TOOL_ENTRYPOINTS[tool]
        entry = getattr(importlib.import_module(module_name), fn_name)
    except Exception as exc:  # noqa: BLE001 - any failure to install the guard means: do not run the tool
        print(
            f"guard: could not install calibration guard ({type(exc).__name__}: {exc}); NOT launching {tool}",
            file=sys.stderr,
        )
        return EXIT_GUARD_FAILED
    print(f"guard: automatic calibration disabled ({', '.join(patched)})", file=sys.stderr)
    sys.argv = [tool, *tool_args]
    try:
        entry()
    except CalibrationBlockedError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_CALIBRATION_BLOCKED
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
