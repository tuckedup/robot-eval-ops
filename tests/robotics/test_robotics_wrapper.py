"""LeRobot subprocess wrapper tests. All "lerobot" executables are FAKE python scripts."""

from __future__ import annotations

import time

import pytest
from robotics_helpers import make_calibration, make_cfg, overrides, read_argv

from robotevalops.adapters.lerobot_wrapper import (
    CONFIRM_TOKEN,
    HardwareGate,
    LeRobotWrapper,
    OperatorAcknowledgement,
    SO101Config,
    discover_lerobot,
    execute_argv,
    load_so101_config,
)
from robotevalops.controllers.base import configs_dir
from robotevalops.errors import (
    CapabilityUnavailableError,
    HardwareRefusedError,
    PreflightFailedError,
    RobotEvalOpsError,
)
from robotevalops.schemas import ControllerType, Provenance

GOOD_GATE = HardwareGate(True, OperatorAcknowledgement("alice", "s1"), True, "s1")


@pytest.fixture
def calib(tmp_path, monkeypatch):
    root = tmp_path / "calib"
    monkeypatch.setenv("HF_LEROBOT_CALIBRATION", str(root))
    return root


def test_example_config_parses():
    cfg = load_so101_config(configs_dir() / "hardware" / "so101.example.yaml")
    assert cfg.follower_id == "my_follower_arm" and "front" in cfg.cameras


def test_argv_is_a_list_with_expected_flags(tmp_path):
    cfg = make_cfg(dataset_root=str(tmp_path / "ds"))
    plan = LeRobotWrapper(cfg, overrides(tmp_path)).build_record(num_episodes=2)
    assert isinstance(plan.argv, list) and all(isinstance(a, str) for a in plan.argv)
    tail = plan.argv[4:]  # fake exe prefix is [python, script, mode, log]
    assert tail[:3] == ["--robot.type=so101_follower", "--robot.port=COM3", "--robot.id=fol_1"]
    assert (
        "--robot.cameras={ front: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30} }"
        in tail
    )
    assert (
        "--teleop.type=so101_leader" in tail and "--teleop.port=COM4" in tail and "--teleop.id=lead_1" in tail
    )
    assert "--dataset.num_episodes=2" in tail and "--dataset.push_to_hub=false" in tail
    assert f"--dataset.root={tmp_path / 'ds'}" in tail
    assert plan.controller_type == ControllerType.TELEOPERATED
    assert plan.provenance == Provenance.PHYSICAL_HARDWARE


def test_teleoperate_and_rollout_builders(tmp_path):
    w = LeRobotWrapper(make_cfg(policy_path="user/my_policy"), overrides(tmp_path))
    tp = w.build_teleoperate()
    assert "--display_data=false" in tp.argv and not any(a.startswith("--dataset") for a in tp.argv)
    ro = w.build_rollout()
    assert "--policy.path=user/my_policy" in ro.argv and ro.controller_type == ControllerType.LEARNED
    assert not any(a.startswith("--teleop") for a in ro.argv)
    with pytest.raises(RobotEvalOpsError, match="policy"):
        LeRobotWrapper(make_cfg(), overrides(tmp_path)).build_rollout()


@pytest.mark.parametrize(
    "bad", ["a; rm -rf /", "a b", "`id`", "$(id)", "a/b", "x\ny", "", "a" * 65, "a&b", "a|b"]
)
def test_injection_like_ids_rejected(bad):
    with pytest.raises(ValueError):
        make_cfg(follower_id=bad)
    with pytest.raises(ValueError):
        make_cfg(leader_id=bad)


@pytest.mark.parametrize(
    "bad",
    ["COM3; calc", "/dev/ttyACM0 ; x", "/dev/../etc/passwd", "COM", "ttyACM0", "/dev/tty`x`", "COM3 COM4"],
)
def test_injection_like_ports_rejected(bad):
    with pytest.raises(ValueError):
        make_cfg(follower_port=bad)


@pytest.mark.parametrize(
    "kw",
    [
        {"dataset_repo_id": "no_slash"},
        {"dataset_repo_id": "a/b; x"},
        {"cameras": {"bad name": {}}},
        {"cameras": {"front": {"index_or_path": "0; rm"}}},
        {"task": "bad\x00task"},
        {"policy_path": "x y"},
    ],
)
def test_other_injection_like_fields_rejected(kw):
    with pytest.raises(ValueError):
        make_cfg(**kw)


def test_task_with_shell_metacharacters_stays_one_argv_element(tmp_path, calib):
    task = "pick $(touch pwned); echo `x` | cat"
    cfg = make_cfg(task=task, dataset_root=str(tmp_path / "ds"))
    make_calibration(calib, cfg)
    w = LeRobotWrapper(cfg, overrides(tmp_path))
    res = w.run(w.build_record(), gate=GOOD_GATE, timeout_s=20)
    assert res.ok
    assert f"--dataset.single_task={task}" in read_argv(tmp_path)  # one element, not interpreted
    assert not (tmp_path / "pwned").exists() and not (tmp_path.parent / "pwned").exists()


def test_refuses_when_calibration_files_missing(tmp_path, calib):
    cfg = make_cfg()
    w = LeRobotWrapper(cfg, overrides(tmp_path))
    with pytest.raises(PreflightFailedError, match="calibration"):
        w.run(w.build_teleoperate(), gate=GOOD_GATE, timeout_s=20)
    assert not (tmp_path / "argv.json").exists()  # subprocess was never started
    checks = w.calibration_checks()
    assert [c.ok for c in checks] == [False, False] and "lerobot-calibrate" in checks[0].detail


def test_runs_fake_exe_when_calibrated_and_gated(tmp_path, calib):
    cfg = make_cfg()
    make_calibration(calib, cfg)
    w = LeRobotWrapper(cfg, overrides(tmp_path))
    res = w.run(w.build_teleoperate(), gate=GOOD_GATE, timeout_s=20)
    assert res.ok and res.returncode == 0 and "fake lerobot ran" in res.stdout_tail
    assert (
        res.provenance == Provenance.PHYSICAL_HARDWARE and res.controller_type == ControllerType.TELEOPERATED
    )
    d = res.as_dict()
    assert d["task_success"] is None and d["argv"] == res.argv


@pytest.mark.parametrize(
    "gate",
    [
        None,
        HardwareGate(False, OperatorAcknowledgement("a", "s1"), True, "s1"),
        HardwareGate(True, None, True, "s1"),
        HardwareGate(True, OperatorAcknowledgement("a", "other"), True, "s1"),
        HardwareGate(True, OperatorAcknowledgement("  ", "s1"), True, "s1"),
        HardwareGate(True, OperatorAcknowledgement("a", "s1"), False, "s1"),
    ],
)
def test_gate_refusals_never_start_the_process(tmp_path, calib, gate):
    cfg = make_cfg()
    make_calibration(calib, cfg)
    w = LeRobotWrapper(cfg, overrides(tmp_path))
    with pytest.raises(HardwareRefusedError):
        w.run(w.build_teleoperate(), gate=gate, timeout_s=5)
    assert not (tmp_path / "argv.json").exists()


def test_calibrate_and_replay_are_dry_run_only(tmp_path, calib):
    cfg = make_cfg()
    make_calibration(calib, cfg)
    w = LeRobotWrapper(cfg, overrides(tmp_path))
    for plan in (w.build_calibrate("follower"), w.build_calibrate("leader"), w.build_replay(0)):
        with pytest.raises(HardwareRefusedError, match="dry-run only"):
            w.run(plan, gate=GOOD_GATE, timeout_s=5)
        with pytest.raises(HardwareRefusedError):
            w.run(plan, gate=None, timeout_s=5, confirm=CONFIRM_TOKEN)
    assert not (tmp_path / "argv.json").exists()
    with pytest.raises(ValueError):
        w.build_replay(-1)


def test_fake_exe_nonzero_is_structured_failure(tmp_path, calib):
    cfg = make_cfg()
    make_calibration(calib, cfg)
    w = LeRobotWrapper(cfg, overrides(tmp_path, mode="nonzero"))
    res = w.run(w.build_record(), gate=GOOD_GATE, timeout_s=20)
    assert not res.ok and res.status == "nonzero_exit" and res.returncode == 3
    assert "motors not found" in res.stderr_tail and res.error


def test_fake_exe_timeout_is_killed(tmp_path, calib):
    cfg = make_cfg()
    make_calibration(calib, cfg)
    w = LeRobotWrapper(cfg, overrides(tmp_path, mode="sleep"))
    t0 = time.monotonic()
    res = w.run(w.build_record(), gate=GOOD_GATE, timeout_s=1.0)
    assert time.monotonic() - t0 < 15
    assert res.status == "timeout" and not res.ok


def test_missing_executable_is_structured_failure(tmp_path, calib):
    cfg = make_cfg()
    make_calibration(calib, cfg)
    w = LeRobotWrapper(cfg, {"lerobot-record": [str(tmp_path / "does_not_exist.exe")]})
    res = w.run(w.build_record(), gate=GOOD_GATE, timeout_s=5)
    assert res.status == "missing_executable" and not res.ok and res.returncode is None


def test_should_stop_kills_process(tmp_path, calib):
    cfg = make_cfg()
    make_calibration(calib, cfg)
    w = LeRobotWrapper(cfg, overrides(tmp_path, mode="sleep"))
    t0 = time.monotonic()
    res = w.run(w.build_record(), gate=GOOD_GATE, timeout_s=30, should_stop=lambda: time.monotonic() - t0 > 1)
    assert res.status == "stopped" and not res.ok and time.monotonic() - t0 < 15


def test_missing_tool_raises_capability_error(tmp_path):
    w = LeRobotWrapper(make_cfg(), {})
    w.info.executables["lerobot-record"] = None
    with pytest.raises(CapabilityUnavailableError, match="lerobot-record"):
        w.build_record()


def test_execute_argv_reports_missing_dataset_as_none(tmp_path):
    res = execute_argv(
        ["python", "-c", "print(1)"], kind="record", timeout_s=20, dataset_path=str(tmp_path / "nope")
    )
    assert res.dataset_path is None


def test_discover_lerobot_uses_overrides(tmp_path):
    info = discover_lerobot({"lerobot-record": ["/x/rec"]})
    assert info.executables["lerobot-record"] == ["/x/rec"]


def test_config_rejects_unknown_keys():
    with pytest.raises(ValueError):
        SO101Config.model_validate(
            {"follower_id": "a", "follower_port": "COM3", "leader_id": "b", "leader_port": "COM4", "bogus": 1}
        )
