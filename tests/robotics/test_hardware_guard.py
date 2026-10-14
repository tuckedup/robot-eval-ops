"""Audit A4: calibration content validation and structural prevention of LeRobot's automatic calibration.

Everything uses FAKE buses and fake executables; no hardware, no serial port, no motor write."""

from __future__ import annotations

import builtins
import contextlib
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
from robotics_helpers import VALID_CALIBRATION, make_calibration, make_cfg

from robotevalops.adapters import lerobot_guard
from robotevalops.adapters.lerobot_wrapper import (
    LeRobotWrapper,
    calibration_candidates,
    validate_calibration_content,
)

lerobot = pytest.importorskip("lerobot")


class FakeBus:
    """Records every call that would touch a motor."""

    def __init__(self, calibrated: bool, calibration: dict | None = None) -> None:
        self.is_calibrated = calibrated
        self.is_connected = False
        self.motors = {n: SimpleNamespace(id=i) for i, n in enumerate(VALID_CALIBRATION, 1)}
        self.calibration = calibration or {}
        self.motor_writes: list[tuple] = []

    def connect(self) -> None:  # opening the port is not a motor write
        self.is_connected = True

    def disable_torque(self, *a, **k):
        self.motor_writes.append(("disable_torque", a))

    @contextlib.contextmanager
    def torque_disabled(self, *a, **k):
        yield  # configure() does this on every normal connect; tracked separately from calibration writes

    def write(self, name, motor, value):
        self.motor_writes.append(("write", name, motor, value))

    def write_calibration(self, cal, cache=True):
        self.motor_writes.append(("write_calibration",))

    def configure_motors(self):
        pass

    def set_half_turn_homings(self):
        self.motor_writes.append(("set_half_turn_homings",))
        return {}

    def record_ranges_of_motion(self, *a):
        self.motor_writes.append(("record_ranges",))
        return {}, {}


def _follower(bus: FakeBus):
    from lerobot.robots.so_follower.so_follower import SOFollower

    r = SOFollower.__new__(SOFollower)
    r.bus, r.cameras, r.id, r.calibration = bus, {}, "fake", bus.calibration
    r.calibration_fpath = None
    return r


def _leader(bus: FakeBus):
    from lerobot.teleoperators.so_leader.so_leader import SOLeader

    t = SOLeader.__new__(SOLeader)
    t.bus, t.id, t.calibration = bus, "fake", bus.calibration
    t.calibration_fpath = None
    return t


@pytest.fixture
def restore_classes(monkeypatch):
    from lerobot.robots.so_follower.so_follower import SOFollower
    from lerobot.teleoperators.so_leader.so_leader import SOLeader

    for cls in (SOFollower, SOLeader):
        for m in ("calibrate", "setup_motors"):
            monkeypatch.setattr(cls, m, getattr(cls, m))  # registers restoration of the originals
    return None


# ----------------------------------------------------------------- calibration file content


def _write(tmp_path, content):
    p = tmp_path / "cal.json"
    p.write_text(json.dumps(content) if not isinstance(content, str) else content, encoding="utf-8")
    return p


def test_valid_calibration_accepted(tmp_path):
    assert validate_calibration_content(_write(tmp_path, VALID_CALIBRATION)) == []


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (lambda c: {}, "empty"),
        (lambda c: {k: v for k, v in c.items() if k != "gripper"}, "'gripper' missing"),
        (lambda c: {**c, "shoulder_pan": {**c["shoulder_pan"], "id": 9}}, "id 9"),
        (lambda c: {**c, "elbow_flex": {**c["elbow_flex"], "range_min": 3000, "range_max": 100}}, "range"),
        (lambda c: {**c, "wrist_flex": {**c["wrist_flex"], "homing_offset": 99999}}, "homing_offset"),
        (lambda c: {**c, "wrist_roll": {"id": 5}}, "missing/non-integer"),
        (lambda c: {**c, "extra_motor": c["gripper"]}, "unexpected motor"),
        (lambda c: "not json", "unreadable"),
        (lambda c: "[1, 2]", "empty"),
    ],
)
def test_invalid_calibration_rejected(tmp_path, mutate, needle):
    problems = validate_calibration_content(_write(tmp_path, mutate(VALID_CALIBRATION)))
    assert problems and any(needle in p for p in problems), problems


def test_empty_json_calibration_fails_preflight_and_refuses_launch(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_LEROBOT_CALIBRATION", str(tmp_path / "cal"))
    cfg = make_cfg()
    make_calibration(tmp_path / "cal", cfg, content={})  # the audit's `{}` files
    w = LeRobotWrapper(cfg, {"lerobot-record": [sys.executable, "-c", "print(1)"]})
    checks = w.calibration_checks()
    assert [c.ok for c in checks] == [False, False]
    assert "not a usable calibration" in checks[0].detail and "empty" in checks[0].detail
    assert all(
        p.is_file() for p in (calibration_candidates("follower", cfg)[0],)
    )  # file exists, still refused


def test_valid_files_pass_content_check(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_LEROBOT_CALIBRATION", str(tmp_path / "cal"))
    cfg = make_cfg()
    make_calibration(tmp_path / "cal", cfg)
    assert all(c.ok for c in LeRobotWrapper(cfg, {}).calibration_checks())


# ----------------------------------------------------------------- the hazard, and the guard


def test_unguarded_lerobot_writes_to_motors_on_empty_calibration(monkeypatch, restore_classes):
    """DEMONSTRATES the hazard the guard exists for (fake bus): connect() with an uncalibrated bus and no
    calibration disables torque and writes Operating_Mode before it asks anything."""
    bus = FakeBus(calibrated=False, calibration={})
    monkeypatch.setattr(builtins, "input", lambda *_a: "")
    with contextlib.suppress(Exception):
        _follower(bus).connect()
    kinds = [w[0] for w in bus.motor_writes]
    assert "disable_torque" in kinds and "write" in kinds


def test_unguarded_lerobot_overwrites_motors_when_file_present_and_enter_pressed(
    monkeypatch, restore_classes
):
    bus = FakeBus(calibrated=False, calibration=dict(VALID_CALIBRATION))
    monkeypatch.setattr(builtins, "input", lambda *_a: "")
    _follower(bus).connect()
    assert ("write_calibration",) in bus.motor_writes


@pytest.mark.parametrize("role", ["follower", "leader"])
@pytest.mark.parametrize("calibration", [{}, dict(VALID_CALIBRATION)], ids=["empty-file", "valid-file"])
def test_guard_blocks_calibration_on_mismatch_with_no_motor_write(
    role, calibration, monkeypatch, restore_classes
):
    patched = lerobot_guard.install_calibration_guard()
    assert {"SOFollower.calibrate", "SOLeader.calibrate", "SOFollower.setup_motors"} <= set(patched)
    bus = FakeBus(calibrated=False, calibration=calibration)
    monkeypatch.setattr(builtins, "input", lambda *_a: pytest.fail("operator prompt must be unreachable"))
    device = _follower(bus) if role == "follower" else _leader(bus)
    with pytest.raises(lerobot_guard.CalibrationBlockedError, match=lerobot_guard.BLOCK_MARKER):
        device.connect()
    assert bus.motor_writes == []  # nothing — no torque change, no register write, no calibration write


def test_guard_allows_normal_connect_when_calibration_matches(restore_classes):
    lerobot_guard.install_calibration_guard()
    bus = FakeBus(calibrated=True, calibration=dict(VALID_CALIBRATION))
    _follower(bus).connect()
    assert not any(
        w[0] in ("write_calibration", "set_half_turn_homings", "record_ranges") for w in bus.motor_writes
    )


def test_guard_setup_motors_is_blocked(restore_classes):
    lerobot_guard.install_calibration_guard()
    with pytest.raises(lerobot_guard.CalibrationBlockedError):
        _follower(FakeBus(True)).setup_motors()


def test_guard_fails_closed_when_target_missing():
    with pytest.raises(RuntimeError, match="refusing to launch unguarded"):
        lerobot_guard.install_calibration_guard((("lerobot.robots.so_follower.so_follower", "NoSuchClass"),))
    with pytest.raises(ModuleNotFoundError):
        lerobot_guard.install_calibration_guard((("lerobot.nope", "X"),))


def test_guard_main_refuses_unknown_tool_and_does_not_run_it(capsys):
    assert lerobot_guard.main(["lerobot-calibrate"]) == lerobot_guard.EXIT_GUARD_FAILED
    assert lerobot_guard.main([]) == lerobot_guard.EXIT_GUARD_FAILED


def test_guard_main_does_not_start_tool_if_guard_cannot_install(monkeypatch, capsys):
    def boom(*_a, **_k):
        raise RuntimeError("cannot patch")

    called = []
    monkeypatch.setattr(lerobot_guard, "install_calibration_guard", boom)
    monkeypatch.setitem(
        lerobot_guard.TOOL_ENTRYPOINTS, "lerobot-record", ("builtins", "print")
    )  # would print if (wrongly) started
    monkeypatch.setattr(builtins, "print", lambda *a, **k: called.append(a) if not k.get("file") else None)
    assert lerobot_guard.main(["lerobot-record", "x"]) == lerobot_guard.EXIT_GUARD_FAILED
    assert called == []  # the entry point (print) was never invoked


def test_guard_main_converts_blocked_calibration_into_exit_code(monkeypatch, restore_classes, capsys):
    def fake_tool():
        _follower(FakeBus(False, {})).connect()

    monkeypatch.setitem(lerobot_guard.TOOL_ENTRYPOINTS, "lerobot-record", (__name__, "_fake_entry"))
    monkeypatch.setattr(sys.modules[__name__], "_fake_entry", fake_tool, raising=False)
    assert lerobot_guard.main(["lerobot-record"]) == lerobot_guard.EXIT_CALIBRATION_BLOCKED
    assert lerobot_guard.BLOCK_MARKER in capsys.readouterr().err


def test_real_launcher_subprocess_installs_guard_then_runs_tool_help():
    """End to end with the REAL installed lerobot: guard installs, then `--help` exits (no connect)."""
    p = subprocess.run(
        [sys.executable, "-m", "robotevalops.adapters.lerobot_guard", "lerobot-record", "--help"],
        capture_output=True,
        text=True,
        timeout=240,
        stdin=subprocess.DEVNULL,
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
    )
    assert "automatic calibration disabled" in p.stderr, p.stderr[-500:]
    assert p.returncode == 0, p.stderr[-800:]


# ----------------------------------------------------------------- wrapper integration


def test_moving_tools_launch_through_guard_unless_overridden():
    w = LeRobotWrapper(make_cfg(), {})
    w.info.executables["lerobot-record"] = ["/usr/bin/lerobot-record"]
    w.info.executables["lerobot-teleoperate"] = ["/usr/bin/lerobot-teleoperate"]
    for plan in (w.build_record(), w.build_teleoperate()):
        assert plan.argv[1:3] == ["-m", "robotevalops.adapters.lerobot_guard"], plan.argv[:4]
        assert plan.argv[3] in ("lerobot-record", "lerobot-teleoperate")
    fake = LeRobotWrapper(make_cfg(), {"lerobot-record": ["/fake/rec"]})
    assert fake.build_record().argv[0] == "/fake/rec"


def test_guard_exit_code_becomes_explicit_calibration_blocked_error(tmp_path):
    from robotevalops.adapters.lerobot_wrapper import execute_argv

    script = tmp_path / "x.py"
    script.write_text(
        "import sys; print('ROBOTEVALOPS_CALIBRATION_BLOCKED: nope', file=sys.stderr); sys.exit(98)"
    )
    res = execute_argv([sys.executable, str(script)], kind="record", timeout_s=30)
    assert res.status == "nonzero_exit" and "calibration blocked" in (res.error or "")


def test_untested_lerobot_version_refuses_to_build_a_moving_command():
    from robotevalops.errors import CapabilityUnavailableError

    w = LeRobotWrapper(make_cfg(), {})
    w.info.version = "0.6.1"  # e.g. what uv.lock resolves on Python 3.12: never tested
    w.info.executables["lerobot-record"] = ["/usr/bin/lerobot-record"]
    with pytest.raises(CapabilityUnavailableError, match="untested"):
        w.build_record()
