# ruff: noqa: E501, B023
"""V4: hardware safety gates. NOTHING here may launch a real lerobot tool: `execute_argv` is replaced by a
recorder in every test (the installed lerobot 0.4.4 executables are real on this machine)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import robotevalops.adapters.hardware_so101 as hw
import robotevalops.adapters.lerobot_wrapper as lw
from robotevalops.adapters.hardware_so101 import SO101HardwareAdapter
from robotevalops.adapters.lerobot_wrapper import (
    HardwareGate,
    LeRobotInfo,
    LeRobotWrapper,
    OperatorAcknowledgement,
    SO101Config,
)
from robotevalops.cli.main import app
from robotevalops.core.runner import Runner
from robotevalops.core.service import EvalService
from robotevalops.errors import HardwareRefusedError, PreflightFailedError
from robotevalops.schemas import (
    ConditionSpec,
    ControllerSpec,
    ControllerType,
    EvalConfig,
    Provenance,
    TerminationReason,
    TrialState,
)

FAKE_TOOLS = {
    t: [f"FAKE-{t}"]
    for t in (
        "lerobot-teleoperate",
        "lerobot-record",
        "lerobot-replay",
        "lerobot-calibrate",
        "lerobot-setup-motors",
    )
}


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[list[str]]:
    """Replace discovery + execution so no real tool can run; record every would-be execution."""
    rec: list[list[str]] = []

    def fake_discover(overrides: Any = None) -> LeRobotInfo:
        return LeRobotInfo("fake", dict(FAKE_TOOLS), True, True, False, None)

    def fake_exec(argv: Any, **kw: Any) -> lw.WrapperResult:
        rec.append([str(a) for a in argv])
        return lw.WrapperResult(kw["kind"], "ok", 0, "", "", 0.0, list(argv), "fake", None)

    monkeypatch.setattr(lw, "discover_lerobot", fake_discover)
    monkeypatch.setattr(lw, "execute_argv", fake_exec)
    monkeypatch.setattr(hw, "default_port_lister", lambda: {"COM3", "COM4"})
    monkeypatch.setattr(hw, "default_camera_probe", lambda cam: (True, "fake camera"))
    monkeypatch.setenv("HF_LEROBOT_CALIBRATION", str(tmp_path / "calib"))  # empty by default
    monkeypatch.delenv("ROBOTEVALOPS_HARDWARE_MODE", raising=False)
    return rec


def _cfg_file(tmp_path: Path, **extra: Any) -> Path:
    import yaml

    d = {
        "follower_id": "fol",
        "follower_port": "COM3",
        "leader_id": "lead",
        "leader_port": "COM4",
        "device_id": "bench",
        "cameras": {"front": {"type": "opencv", "index_or_path": 0}},
        **extra,
    }
    p = tmp_path / "so101.yaml"
    p.write_text(yaml.safe_dump(d), encoding="utf-8")
    return p


_VALID_CAL = {
    n: {"id": i, "drive_mode": 0, "homing_offset": 5 * i, "range_min": 100 * i, "range_max": 100 * i + 2000}
    for i, n in enumerate(
        ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"), start=1
    )
}


def _calibrate(tmp_path: Path) -> None:
    for sub, name, ident in (("robots", "so_follower", "fol"), ("teleoperators", "so_leader", "lead")):
        d = tmp_path / "calib" / sub / name
        d.mkdir(parents=True, exist_ok=True)
        # structurally valid (SYNTHETIC) calibration: an empty {} file is now correctly refused
        (d / f"{ident}.json").write_text(json.dumps(_VALID_CAL), encoding="utf-8")


runner = CliRunner()


@pytest.mark.parametrize("cmd", ["teleop", "record", "rollout"])
@pytest.mark.parametrize(
    "flags",
    [
        [],
        ["--hardware-mode"],
        ["--ack-operator", "alice"],
        ["--hardware-mode", "--ack-operator", "  "],
    ],
)
def test_cli_refuses_without_mode_and_ack(cmd, flags, calls, tmp_path: Path) -> None:
    _calibrate(tmp_path)
    extra = ["--policy-path", "local/pol"] if cmd == "rollout" else []
    r = runner.invoke(app, ["robot", cmd, "--config", str(_cfg_file(tmp_path)), *flags, *extra])
    assert r.exit_code != 0, r.output
    assert calls == []


@pytest.mark.parametrize("cmd", ["teleop", "record", "rollout"])
def test_cli_refuses_when_preflight_fails_even_with_mode_and_ack(cmd, calls, tmp_path, monkeypatch) -> None:
    _calibrate(tmp_path)
    monkeypatch.setattr(hw, "default_port_lister", lambda: set())  # ports unplugged -> preflight fails
    extra = ["--policy-path", "local/pol"] if cmd == "rollout" else []
    r = runner.invoke(
        app,
        [
            "robot",
            cmd,
            "--config",
            str(_cfg_file(tmp_path)),
            "--hardware-mode",
            "--ack-operator",
            "alice",
            *extra,
        ],
    )
    assert r.exit_code != 0 and calls == []
    assert "preflight" in r.output.lower()


@pytest.mark.parametrize("cmd", ["teleop", "record", "rollout"])
def test_cli_refuses_when_joint_calibration_missing(cmd, calls, tmp_path) -> None:
    """No calibration files => lerobot would auto-start motor calibration. Must refuse (positive control below)."""
    extra = ["--policy-path", "local/pol"] if cmd == "rollout" else []
    r = runner.invoke(
        app,
        [
            "robot",
            cmd,
            "--config",
            str(_cfg_file(tmp_path)),
            "--hardware-mode",
            "--ack-operator",
            "alice",
            *extra,
        ],
    )
    assert r.exit_code != 0 and calls == []
    assert "calibration" in r.output.lower()


@pytest.mark.parametrize("cmd", ["teleop", "record", "rollout"])
def test_positive_control_all_gates_satisfied_executes_exactly_once(cmd, calls, tmp_path) -> None:
    _calibrate(tmp_path)
    extra = ["--policy-path", "local/pol"] if cmd == "rollout" else []
    r = runner.invoke(
        app,
        [
            "robot",
            cmd,
            "--config",
            str(_cfg_file(tmp_path)),
            "--hardware-mode",
            "--ack-operator",
            "alice",
            *extra,
        ],
    )
    assert r.exit_code == 0, r.output
    assert len(calls) == 1
    assert calls[0][0] in ("FAKE-lerobot-teleoperate", "FAKE-lerobot-record")
    assert not any(
        a in ("FAKE-lerobot-calibrate", "FAKE-lerobot-replay", "FAKE-lerobot-setup-motors")
        for c in calls
        for a in c[:1]
    )


def test_dry_run_never_executes(calls, tmp_path) -> None:
    for cmd in ("teleop", "record"):
        r = runner.invoke(
            app,
            [
                "robot",
                cmd,
                "--config",
                str(_cfg_file(tmp_path)),
                "--dry-run",
                "--hardware-mode",
                "--ack-operator",
                "alice",
            ],
        )
        assert r.exit_code == 0 and calls == [], r.output


def test_cli_exposes_no_calibrate_replay_setup_or_flash_command() -> None:
    from typer.main import get_command

    root = get_command(app)
    names: set[str] = set()

    def walk(cmd: Any, prefix: str = "") -> None:
        for n, c in getattr(cmd, "commands", {}).items():
            names.add(f"{prefix}{n}")
            walk(c, f"{prefix}{n} ")

    walk(root)
    assert not [n for n in names if re.search(r"calibrat|replay|setup|flash|motor", n)], names


def test_calibrate_and_replay_need_gate_and_token_even_from_library(calls, tmp_path) -> None:
    cfg = SO101Config.model_validate(
        {"follower_id": "fol", "follower_port": "COM3", "leader_id": "lead", "leader_port": "COM4"}
    )
    w = LeRobotWrapper(cfg)
    ok_gate = HardwareGate(True, OperatorAcknowledgement("a", "s"), True, "s")
    for plan in (w.build_calibrate("follower"), w.build_replay(0)):
        with pytest.raises(HardwareRefusedError):
            w.run(plan, gate=None, timeout_s=1)
        with pytest.raises(HardwareRefusedError):
            w.run(plan, gate=HardwareGate(False, None, False), timeout_s=1)
        with pytest.raises(HardwareRefusedError):  # gate ok, token missing
            w.run(plan, gate=ok_gate, timeout_s=1)
        with pytest.raises(HardwareRefusedError):  # wrong token
            w.run(plan, gate=ok_gate, timeout_s=1, confirm="yes")
    assert calls == []


def _adapter(tmp_path: Path, **kw: Any) -> SO101HardwareAdapter:
    cfg = SO101Config.model_validate(
        {
            "follower_id": "fol",
            "follower_port": "COM3",
            "leader_id": "lead",
            "leader_port": "COM4",
            "cameras": {"front": {}},
        }
    )
    return SO101HardwareAdapter(cfg, **kw)


def test_adapter_motion_methods_refuse_each_missing_gate_element(calls, tmp_path) -> None:
    _calibrate(tmp_path)
    ctl_spec = ControllerSpec(controller_id="t", type=ControllerType.TELEOPERATED, version="1")

    class C:
        spec = ctl_spec

    cond = ConditionSpec(name="k", kind="nominal")
    ack = OperatorAcknowledgement("alice", "S1")
    variants = {
        "no_mode": dict(hardware_mode=False, acknowledgement=ack, session_id="S1"),
        "no_ack": dict(hardware_mode=True, acknowledgement=None, session_id="S1"),
        "blank_operator": dict(
            hardware_mode=True, acknowledgement=OperatorAcknowledgement(" ", "S1"), session_id="S1"
        ),
        "other_session_ack": dict(
            hardware_mode=True, acknowledgement=OperatorAcknowledgement("a", "S2"), session_id="S1"
        ),
    }
    for name, kw in variants.items():
        ad = _adapter(tmp_path, **kw)
        assert ad.preflight().ok, name  # preflight itself is non-moving and passes
        for fn in (lambda: ad.reset(cond, 0), lambda: ad.run_episode(C(), tmp_path / "o", 5, 2)):
            with pytest.raises(HardwareRefusedError):
                fn()
    # preflight never run on this instance => refused even with mode+ack
    ad = _adapter(tmp_path, hardware_mode=True, acknowledgement=ack, session_id="S1")
    with pytest.raises(HardwareRefusedError):
        ad.reset(cond, 0)
    with pytest.raises(HardwareRefusedError):
        ad.run_episode(C(), tmp_path / "o", 5, 2)
    assert calls == []
    # failed preflight (unplugged) => refused
    import robotevalops.adapters.hardware_so101 as m

    ad2 = _adapter(
        tmp_path, hardware_mode=True, acknowledgement=ack, session_id="S1", port_lister=lambda: set()
    )
    assert not ad2.preflight().ok
    with pytest.raises(HardwareRefusedError):
        ad2.run_episode(C(), tmp_path / "o", 5, 2)
    assert m is hw and calls == []
    # positive control
    ad3 = _adapter(tmp_path, hardware_mode=True, acknowledgement=ack, session_id="S1")
    assert ad3.preflight().ok
    res = ad3.run_episode(C(), tmp_path / "o3", 5, 2)
    assert len(calls) == 1 and res.task_success is None  # never judges success


def test_ack_for_other_session_refused_even_when_adapter_session_id_unset(calls, tmp_path) -> None:
    _calibrate(tmp_path)
    ad = _adapter(tmp_path, hardware_mode=True, acknowledgement=OperatorAcknowledgement("a", "OTHER"))
    assert ad.preflight().ok
    with pytest.raises(HardwareRefusedError):
        ad.gate().require()


def _hw_session(tmp_path: Path, svc: EvalService, cfg_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ROBOTEVALOPS_SO101_CONFIG", str(cfg_path))
    cfg = EvalConfig(
        name="hw",
        provenance=Provenance.PHYSICAL_HARDWARE,
        backend="so101_lerobot",
        controllers=[ControllerSpec(controller_id="t", type=ControllerType.TELEOPERATED, version="1")],
        conditions=[ConditionSpec(name="k", kind="nominal")],
        trials_per_condition=2,
    )
    s = svc.create_session(
        "hw", Provenance.PHYSICAL_HARDWARE, "so101_lerobot", eval_config=cfg, device_id="bench"
    )
    svc.plan_trials(s.session_id, cfg)
    return s


def test_session_run_physical_cli_gates(calls, tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    svc = EvalService(home)
    s = _hw_session(tmp_path, svc, _cfg_file(tmp_path), monkeypatch)
    _calibrate(tmp_path)
    sid = s.session_id
    base = ["session", "run", sid, "--home", str(home)]
    r = runner.invoke(app, base)  # no ack
    assert r.exit_code != 0 and "acknowledg" in r.output.lower()
    svc.acknowledge_operator(sid, "alice")
    r = runner.invoke(app, base)  # ack, no preflight (state PLANNED)
    assert r.exit_code != 0
    assert all(t.state == TrialState.PLANNED for t in svc.list_trials(sid)) and calls == []
    # preflight recorded (service call stands in for the CLI preflight on a machine with the arm)
    svc.mark_preflight_passed(sid)
    # hardware mode env NOT set: Runner reaches adapter.reset -> HardwareRefusedError -> must not execute lerobot
    r = runner.invoke(app, base)
    assert calls == [], "a lerobot tool was launched without hardware mode"
    trials = svc.list_trials(sid)
    first = trials[0]
    # VF-08 (fixed): a gate refusal is NOT an attempt: no started_at, no infra failure, nothing counted.
    assert first.started_at is None
    assert first.state == TrialState.PREFLIGHT
    assert first.termination_reason != TerminationReason.INFRA_FAILURE
    assert trials[1].state == TrialState.PLANNED
    assert svc.get_session(sid).requires_fresh_preflight is False


def test_runner_refuses_physical_session_without_ack_or_preflight(calls, tmp_path, monkeypatch) -> None:
    svc = EvalService(tmp_path / "home")
    s = _hw_session(tmp_path, svc, _cfg_file(tmp_path), monkeypatch)
    rn = Runner(svc, lambda sess: _adapter(tmp_path), lambda spec: None)  # type: ignore[arg-type,return-value]
    with pytest.raises(HardwareRefusedError):
        rn.run_session(s.session_id)
    svc.acknowledge_operator(s.session_id, "a")
    with pytest.raises(PreflightFailedError):
        rn.run_session(s.session_id)
    assert calls == []


# ---------------------------------------------------------------- injection
@pytest.mark.parametrize(
    "field",
    ["follower_id", "leader_id", "follower_port", "leader_port", "dataset_repo_id"],
)
@pytest.mark.parametrize(
    "evil",
    [
        "x; rm -rf /",
        "a b",
        "$(whoami)",
        "`id`",
        "COM3 --robot.id=evil",
        "../../etc/passwd",
        "a\nb",
        "x&&y",
        "--robot.port=COM9",
        "COM3\x00",
        "/dev/../tty",
        "x|y",
        "ok'bad",
        'a"b',
    ],
)
def test_config_fields_reject_injection_strings(field: str, evil: str) -> None:
    base = {"follower_id": "fol", "follower_port": "COM3", "leader_id": "lead", "leader_port": "COM4"}
    base[field] = evil
    with pytest.raises(ValueError):
        SO101Config.model_validate(base)


@pytest.mark.parametrize("evil", ["x, type: evil}", "a}", "{a", "a b", "a;b", "$(id)", "a\nb", "a,b"])
def test_camera_fields_reject_injection(evil: str) -> None:
    base = {"follower_id": "fol", "follower_port": "COM3", "leader_id": "lead", "leader_port": "COM4"}
    with pytest.raises(ValueError):
        SO101Config.model_validate({**base, "cameras": {"front": {"index_or_path": evil}}})
    with pytest.raises(ValueError):
        SO101Config.model_validate({**base, "cameras": {evil: {}}})


@pytest.mark.parametrize("evil", ["x\n--robot.type=evil", "a\x07b", "", "   "])
def test_task_rejects_control_chars(evil: str) -> None:
    base = {"follower_id": "fol", "follower_port": "COM3", "leader_id": "lead", "leader_port": "COM4"}
    with pytest.raises(ValueError):
        SO101Config.model_validate({**base, "task": evil})


def test_odd_but_allowed_values_stay_single_argv_tokens(calls) -> None:
    """Task text with spaces/dashes/quotes is one argv element; no shell is involved."""
    task = "pick --dataset.push_to_hub=true; echo hi && 'x'"
    cfg = SO101Config.model_validate(
        {
            "follower_id": "fol",
            "follower_port": "COM3",
            "leader_id": "lead",
            "leader_port": "COM4",
            "task": task,
        }
    )
    plan = LeRobotWrapper(cfg).build_record()
    assert f"--dataset.single_task={task}" in plan.argv
    assert plan.argv.count("--dataset.push_to_hub=false") == 1
    assert not any(a == "--dataset.push_to_hub=true" for a in plan.argv)


@pytest.mark.parametrize("field", ["follower_id", "follower_port", "dataset_repo_id"])
def test_trailing_newline_is_rejected(field: str) -> None:
    base = {"follower_id": "fol", "follower_port": "COM3", "leader_id": "lead", "leader_port": "COM4"}
    value = {"follower_id": "fol\n", "follower_port": "COM3\n", "dataset_repo_id": "a/b\n"}[field]
    with pytest.raises(ValueError):
        SO101Config.model_validate({**base, field: value})
