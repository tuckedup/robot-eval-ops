"""SO-101 hardware adapter, registry, dataset helper and CLI tests.

Everything uses FAKE executables, fake port listers and fake camera probes. Nothing here touches
or verifies real hardware.
"""

from __future__ import annotations

import json

import pytest
from robotics_helpers import fake_info, make_calibration, make_cfg, overrides
from typer.testing import CliRunner

import robotevalops.adapters.lerobot_wrapper as lw
from robotevalops.adapters.base import Action, PreflightResult
from robotevalops.adapters.hardware_so101 import SO101HardwareAdapter
from robotevalops.adapters.lerobot_dataset import inspect_dataset, split_episodes
from robotevalops.adapters.lerobot_wrapper import OperatorAcknowledgement
from robotevalops.adapters.registry import get_adapter, get_controller, list_backends
from robotevalops.cli.robot_cmds import app
from robotevalops.controllers.base import StopRequestedError
from robotevalops.controllers.external import ExternalLeRobotController
from robotevalops.errors import CapabilityUnavailableError, HardwareRefusedError, RobotEvalOpsError
from robotevalops.schemas import (
    ConditionSpec,
    ControllerSpec,
    ControllerType,
    Provenance,
    TerminationReason,
)

COND = ConditionSpec(name="nominal", kind="nominal")
TELEOP = ControllerSpec(controller_id="teleop_operator", type=ControllerType.TELEOPERATED, version="1")
ACK = OperatorAcknowledgement("alice", "s1")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Fake-lerobot environment: calibration root in tmp, discovery replaced by a fake LeRobotInfo."""
    root = tmp_path / "calib"
    monkeypatch.setenv("HF_LEROBOT_CALIBRATION", str(root))
    ov = overrides(tmp_path, mode="dataset")
    monkeypatch.setattr(lw, "discover_lerobot", lambda overrides=None: fake_info(overrides or ov))
    cfg = make_cfg()
    return {"root": root, "ov": ov, "cfg": cfg}


def make_adapter(env, **kw):
    kw.setdefault("port_lister", lambda: {"COM3", "COM4"})
    kw.setdefault("camera_probe", lambda cam: (True, "FAKE probe opened"))
    kw.setdefault("overrides", env["ov"])
    return SO101HardwareAdapter(env["cfg"], session_id="s1", **kw)


def test_provenance_and_name(env):
    a = make_adapter(env)
    assert a.provenance == Provenance.PHYSICAL_HARDWARE and a.name == "so101_lerobot"


def test_preflight_reports_each_missing_item_with_actionable_message(env):
    a = make_adapter(env, port_lister=lambda: set(), camera_probe=lambda c: (False, "cannot open camera 0"))
    pre = a.preflight()
    assert not pre.ok
    failed = {c.name: c.detail for c in pre.failures()}
    assert set(failed) == {
        "follower_port_present",
        "leader_port_present",
        "follower_joint_calibration_file",
        "leader_joint_calibration_file",
        "camera_front_openable",
    }
    assert "lerobot-find-port" in failed["follower_port_present"]
    assert "lerobot-calibrate" in failed["follower_joint_calibration_file"]


def test_preflight_passes_with_everything_present(env):
    make_calibration(env["root"], env["cfg"])
    assert make_adapter(env).preflight().ok


def test_preflight_without_pyserial_or_cameras_fails_clearly(env):
    def boom() -> set[str]:
        raise CapabilityUnavailableError("pyserial is not installed")

    make_calibration(env["root"], env["cfg"])
    cfg = make_cfg(cameras={})
    a = SO101HardwareAdapter(cfg, port_lister=boom, overrides=env["ov"])
    pre = a.preflight()
    d = {c.name: c for c in pre.checks}
    assert not d["follower_port_present"].ok and "pyserial" in d["follower_port_present"].detail
    assert not d["cameras_configured"].ok


def _all_motion_calls(a, tmp_path):
    ctl = type("C", (), {"spec": TELEOP})()
    return [
        lambda: a.reset(COND, 1),
        lambda: a.act(Action([0.0])),
        lambda: a.step(),
        lambda: a.run_episode(ctl, tmp_path / "ep", 5.0, 2.0),
    ]


def test_motion_refused_without_hardware_mode(env, tmp_path):
    make_calibration(env["root"], env["cfg"])
    a = make_adapter(env, acknowledgement=ACK)
    assert a.preflight().ok
    for call in _all_motion_calls(a, tmp_path):
        with pytest.raises(HardwareRefusedError, match="hardware mode"):
            call()


def test_motion_refused_without_acknowledgement(env, tmp_path):
    make_calibration(env["root"], env["cfg"])
    a = make_adapter(env, hardware_mode=True)
    assert a.preflight().ok
    for call in _all_motion_calls(a, tmp_path):
        with pytest.raises(HardwareRefusedError, match="acknowledgement"):
            call()


def test_motion_refused_with_acknowledgement_for_other_session(env, tmp_path):
    make_calibration(env["root"], env["cfg"])
    a = make_adapter(env, hardware_mode=True, acknowledgement=OperatorAcknowledgement("a", "other-session"))
    a.preflight()
    with pytest.raises(HardwareRefusedError, match="different session"):
        a.reset(COND, 1)


def test_motion_refused_without_preflight_or_with_failing_preflight(env, tmp_path):
    a = make_adapter(env, hardware_mode=True, acknowledgement=ACK)
    for call in _all_motion_calls(a, tmp_path):
        with pytest.raises(HardwareRefusedError, match="preflight"):
            call()
    a.preflight()  # calibration files are missing -> failing preflight
    assert not a._preflight.ok  # type: ignore[union-attr]
    with pytest.raises(HardwareRefusedError, match="preflight"):
        a.reset(COND, 1)


def test_run_episode_delegates_to_fake_wrapper_and_never_judges_success(env, tmp_path):
    make_calibration(env["root"], env["cfg"])
    a = make_adapter(env, hardware_mode=True, acknowledgement=ACK)
    assert a.preflight().ok
    assert a.reset(COND, 1).state == {}
    ctl = ExternalLeRobotController(TELEOP)
    res = a.run_episode(ctl, tmp_path / "ep", 5.0, 2.0)
    assert res.task_success is None  # video-backed operator scoring required
    assert res.intervention_detected is False and res.evidence["intervention"] == "unknown"
    assert res.termination_reason == TerminationReason.TIMEOUT
    assert res.recording.video_kind == "physical_camera" and res.recording.video_relpath == "video.mp4"
    assert (tmp_path / "ep" / "video.mp4").read_bytes() == b"FAKE-VIDEO-BYTES"
    assert res.evidence["wrapper"]["task_success"] is None
    assert res.evidence["wrapper"]["provenance"] == "physical_hardware"


def test_run_episode_without_video_is_recording_failure(env, tmp_path):
    make_calibration(env["root"], env["cfg"])
    ov = overrides(tmp_path, mode="dataset_no_video")
    a = make_adapter(env, hardware_mode=True, acknowledgement=ACK, overrides=ov)
    assert a.preflight().ok
    res = a.run_episode(ExternalLeRobotController(TELEOP), tmp_path / "ep", 5.0, 2.0)
    assert res.termination_reason == TerminationReason.RECORDING_FAILURE and res.task_success is None


def test_run_episode_subprocess_failure_is_infra_failure(env, tmp_path):
    make_calibration(env["root"], env["cfg"])
    ov = overrides(tmp_path, mode="nonzero")
    a = make_adapter(env, hardware_mode=True, acknowledgement=ACK, overrides=ov)
    assert a.preflight().ok
    res = a.run_episode(ExternalLeRobotController(TELEOP), tmp_path / "ep", 5.0, 2.0)
    assert res.termination_reason == TerminationReason.INFRA_FAILURE
    assert res.task_success is None and res.error


def test_scripted_controller_not_runnable_on_hardware(env, tmp_path):
    make_calibration(env["root"], env["cfg"])
    a = make_adapter(env, hardware_mode=True, acknowledgement=ACK)
    a.preflight()
    spec = ControllerSpec(controller_id="s", type=ControllerType.SCRIPTED, version="1")
    with pytest.raises(RobotEvalOpsError, match="scripted"):
        a.run_episode(type("C", (), {"spec": spec})(), tmp_path / "ep", 5, 2)


def test_request_stop_idempotent_and_blocks_commands(env, tmp_path):
    make_calibration(env["root"], env["cfg"])
    a = make_adapter(env, hardware_mode=True, acknowledgement=ACK)
    a.preflight()
    assert "NOT an emergency stop" in SO101HardwareAdapter.request_stop.__doc__  # type: ignore[operator]
    a.request_stop()
    a.request_stop()
    assert a.stop_requested
    with pytest.raises(StopRequestedError):
        a.reset(COND, 1)
    with pytest.raises(StopRequestedError):
        a.act(Action([0.0]))
    with pytest.raises(StopRequestedError):
        a.run_episode(ExternalLeRobotController(TELEOP), tmp_path / "ep", 5, 2)


def test_preflight_result_type(env):
    assert isinstance(make_adapter(env).preflight(), PreflightResult)


# ----------------------------------------------------------------------------- registry


def test_registry_mock_and_unknown():
    assert get_adapter("mock", None).name == "mock"
    with pytest.raises(CapabilityUnavailableError, match="unknown backend"):
        get_adapter("nope", None)
    with pytest.raises(CapabilityUnavailableError, match="unknown backend"):
        get_controller(ControllerSpec(controller_id="x", type=ControllerType.SCRIPTED, version="1"), "nope")
    with pytest.raises(CapabilityUnavailableError, match="import-only"):
        get_adapter("lerobot_import", None)


def test_registry_pybullet_missing_is_clear_error(monkeypatch):
    import robotevalops.adapters.registry as reg

    monkeypatch.setattr(reg.importlib.util, "find_spec", lambda name: None)
    with pytest.raises(CapabilityUnavailableError, match="pybullet is not installed"):
        get_adapter("pybullet_panda", None)
    spec = ControllerSpec(controller_id="x", type=ControllerType.SCRIPTED, version="1")
    with pytest.raises(CapabilityUnavailableError, match="pybullet"):
        get_controller(spec, "pybullet_panda")
    b = {x["backend"]: x for x in list_backends()}
    assert b["pybullet_panda"]["available"] is False and b["mock"]["available"] is True


def test_registry_learned_controller_not_available_for_sim():
    spec = ControllerSpec(
        controller_id="l", type=ControllerType.LEARNED, version="1", artifact_sha256="a" * 64
    )
    pytest.importorskip("pybullet")
    with pytest.raises(CapabilityUnavailableError, match="learned"):
        get_controller(spec, "pybullet_panda")


def test_registry_so101_needs_config_and_never_enables_motion_by_default(tmp_path, monkeypatch, env):
    monkeypatch.setenv("ROBOTEVALOPS_SO101_CONFIG", str(tmp_path / "missing.yaml"))
    with pytest.raises(CapabilityUnavailableError, match="config"):
        get_adapter("so101_lerobot", None)
    cfg_path = tmp_path / "so101.yaml"
    cfg_path.write_text(
        "follower_id: f\nfollower_port: COM3\nleader_id: l\nleader_port: COM4\n", encoding="utf-8"
    )
    monkeypatch.setenv("ROBOTEVALOPS_SO101_CONFIG", str(cfg_path))
    monkeypatch.delenv("ROBOTEVALOPS_HARDWARE_MODE", raising=False)
    sess = type("S", (), {"session_id": "s1", "operator": "alice", "operator_ack_at": None})()
    adapter = get_adapter("so101_lerobot", sess)
    assert isinstance(adapter, SO101HardwareAdapter) and adapter.hardware_mode is False
    with pytest.raises(HardwareRefusedError):
        adapter.reset(COND, 1)
    assert isinstance(get_controller(TELEOP, "so101_lerobot"), ExternalLeRobotController)


# ----------------------------------------------------------------------------- datasets


def test_episode_split_keeps_whole_episodes_and_is_deterministic():
    eps = list(range(20))
    s1 = split_episodes(eps, 0.25, seed=7)
    s2 = split_episodes(list(reversed(eps)), 0.25, seed=7)
    assert s1 == s2
    assert len(s1["eval"]) == 5 and len(s1["train"]) == 15
    assert set(s1["train"]).isdisjoint(s1["eval"]) and sorted(s1["train"] + s1["eval"]) == eps
    assert split_episodes(eps, 0.25, seed=8) != s1
    # frames are mapped by their episode index, so adjacent frames of one episode share a split
    frame_episode = [f // 10 for f in range(200)]
    assign = {e: "eval" for e in s1["eval"]} | {e: "train" for e in s1["train"]}
    for a, b in zip(frame_episode, frame_episode[1:], strict=False):
        if a == b:
            assert assign[a] == assign[b]


def test_episode_split_edge_cases():
    with pytest.raises(RobotEvalOpsError):
        split_episodes([0], 0.2)
    with pytest.raises(RobotEvalOpsError):
        split_episodes([0, 1, 2], 1.5)
    s = split_episodes([0, 1], 0.2)
    assert len(s["eval"]) == 1 and len(s["train"]) == 1


def test_inspect_dataset_reads_info_json(tmp_path):
    (tmp_path / "meta").mkdir()
    (tmp_path / "meta" / "info.json").write_text(
        json.dumps(
            {
                "codebase_version": "v3.0",
                "robot_type": "so101_follower",
                "fps": 30,
                "total_episodes": 4,
                "total_frames": 400,
                "features": {"action": {}, "observation.state": {}},
            }
        ),
        encoding="utf-8",
    )
    s = inspect_dataset(tmp_path)
    assert (
        s["total_episodes"] == 4 and s["fps"] == 30 and s["feature_names"] == ["action", "observation.state"]
    )
    assert s["provenance"] == "imported_real_recording"
    with pytest.raises(RobotEvalOpsError, match="meta/info.json"):
        inspect_dataset(tmp_path / "nowhere")


# ----------------------------------------------------------------------------- CLI

runner = CliRunner()


def test_cli_adapters_and_import_without_dataset():
    r = runner.invoke(app, ["adapters", "--json"])
    assert r.exit_code == 0 and {b["backend"] for b in json.loads(r.stdout)} >= {"mock", "pybullet_panda"}
    r = runner.invoke(app, ["import-dataset", "--json"])
    assert r.exit_code == 0 and json.loads(r.stdout)["dataset"] is None


def test_cli_import_dataset_without_episode_metadata_is_rejected_and_never_invents_ids(tmp_path):
    (tmp_path / "meta").mkdir()
    (tmp_path / "meta" / "info.json").write_text(
        json.dumps({"total_episodes": 10, "fps": 30}), encoding="utf-8"
    )
    r = runner.invoke(app, ["import-dataset", "--path", str(tmp_path), "--json"])
    out = json.loads(r.stdout)
    assert r.exit_code == 1 and out["status"] == "rejected"
    assert (
        out["accepted_episodes"] == [] and out["split"].get("train") is None
    )  # no range(total_episodes) fabrication


def test_cli_dry_run_prints_argv_and_does_not_execute(tmp_path):
    r = runner.invoke(app, ["record", "--dry-run", "--json"])
    out = json.loads(r.stdout)
    assert r.exit_code == 0 and out["executed"] is False and isinstance(out["argv"], list)
    assert "--robot.type=so101_follower" in out["argv"] and out["would_refuse"] is True


def test_cli_refuses_without_hardware_mode_and_ack():
    r = runner.invoke(app, ["teleop", "--json"])
    assert r.exit_code == 2 and "--hardware-mode" in r.stdout
    r = runner.invoke(app, ["teleop", "--hardware-mode", "--json"])
    assert r.exit_code == 2 and "--ack-operator" in r.stdout
    r = runner.invoke(app, ["rollout", "--hardware-mode", "--ack-operator", "alice", "--json"])
    assert r.exit_code == 2  # no policy path / failing preflight: never runs


def test_cli_hardware_check_fails_on_this_machine_without_hardware():
    r = runner.invoke(app, ["hardware-check", "--json"])
    assert r.exit_code == 1 and json.loads(r.stdout)["ok"] is False


def test_cli_lerobot_info():
    r = runner.invoke(app, ["lerobot-info", "--json"])
    d = json.loads(r.stdout)
    assert r.exit_code == 0 and "sources" in d and "lerobot_rollout_tool_present" in d


# ------------------------------------------------------- verification-round fixes (VF-07/08/09/17)


def test_ack_bound_to_session_refused_when_gate_session_unset(env):
    make_calibration(env["root"], env["cfg"])
    a = SO101HardwareAdapter(
        env["cfg"],
        hardware_mode=True,
        acknowledgement=OperatorAcknowledgement("a", "S9"),
        overrides=env["ov"],
        port_lister=lambda: {"COM3", "COM4"},
        camera_probe=lambda c: (True, "FAKE"),
    )
    assert a.preflight().ok
    with pytest.raises(HardwareRefusedError, match="session id is unset"):
        a.gate().require()


def test_check_motion_allowed_is_non_moving_and_gated(env):
    make_calibration(env["root"], env["cfg"])
    a = make_adapter(env, hardware_mode=True, acknowledgement=ACK)
    with pytest.raises(HardwareRefusedError, match="preflight"):
        a.check_motion_allowed()
    assert a.preflight().ok
    assert a.check_motion_allowed() is None
    b = make_adapter(env, acknowledgement=ACK)
    b.preflight()
    with pytest.raises(HardwareRefusedError, match="hardware mode"):
        b.check_motion_allowed()


@pytest.mark.parametrize(
    "kw",
    [
        {"follower_id": "fol\n"},
        {"follower_port": "COM3\n"},
        {"dataset_repo_id": "a/b\n"},
        {"leader_id": "x\n"},
    ],
)
def test_trailing_newline_rejected_fullmatch(kw):
    with pytest.raises(ValueError):
        make_cfg(**kw)


def _real_mp4(path, n):
    import numpy as np

    from robotevalops.recording.writers import TrialRecorder

    rec = TrialRecorder(path.parent, 10, ["s"], ["a"], Provenance.MOCK, frame_size=(32, 24))
    for k in range(n):
        rec.add(k / 10, np.full((24, 32, 3), k * 20, dtype=np.uint8), [0.0], [0.0])
    rec.close(n)


def test_trace_written_from_synthetic_lerobot_style_parquet_exactly(env, tmp_path, monkeypatch):
    """SYNTHETIC dataset fixture written by the fake exe; trace values must be copied exactly."""
    pytest.importorskip("pyarrow")
    vid_dir = tmp_path / "src"
    vid_dir.mkdir()
    _real_mp4(vid_dir / "video.mp4", 4)
    monkeypatch.setenv("FAKE_VIDEO", str(vid_dir / "video.mp4"))
    make_calibration(env["root"], env["cfg"])
    ov = overrides(tmp_path, mode="dataset_parquet")
    a = make_adapter(env, hardware_mode=True, acknowledgement=ACK, overrides=ov)
    assert a.preflight().ok
    res = a.run_episode(ExternalLeRobotController(TELEOP), tmp_path / "ep", 5.0, 2.0)
    lines = (tmp_path / "ep" / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0])
    rows = [json.loads(x) for x in lines[1:]]
    assert header["state_names"] == ["j0", "j1"] and header["action_names"] == ["a0", "a1"]
    assert header["provenance"] == "physical_hardware" and header["fps"] == 10.0
    assert [r["t"] for r in rows] == [0.0, 0.1, 0.2, 0.3]
    assert rows[1]["state"] == [0.5, 1.5] and rows[2]["action"] == [0.5, 0.6]
    assert rows[3]["state"][0] != rows[3]["state"][0]  # NaN preserved, not repaired
    rec = res.recording
    assert rec.trace_relpath == "trace.jsonl" and rec.trace_rows == 4 and rec.frames_expected == 4
    assert rec.frames_written == 4 and rec.completeness == 1.0
    assert res.task_success is None


def test_trace_absent_and_reported_when_parquet_columns_missing(env, tmp_path):
    pytest.importorskip("pyarrow")
    import pandas as pd

    root = tmp_path / "ds"
    (root / "data").mkdir(parents=True)
    pd.DataFrame({"timestamp": [0.0, 0.1]}).to_parquet(root / "data" / "f.parquet")
    from robotevalops.adapters.lerobot_dataset import episode_to_trace

    r = episode_to_trace(root, tmp_path / "trace.jsonl")
    assert r["ok"] is False and "missing columns" in r["reason"] and not (tmp_path / "trace.jsonl").exists()
    r2 = episode_to_trace(tmp_path / "empty", tmp_path / "t2.jsonl")
    assert r2["ok"] is False and "no data" in r2["reason"]


def test_fake_video_bytes_without_parquet_leave_trace_absent_with_evidence(env, tmp_path):
    make_calibration(env["root"], env["cfg"])
    a = make_adapter(env, hardware_mode=True, acknowledgement=ACK)
    assert a.preflight().ok
    res = a.run_episode(ExternalLeRobotController(TELEOP), tmp_path / "ep", 5.0, 2.0)
    assert res.recording.trace_relpath is None and not (tmp_path / "ep" / "trace.jsonl").exists()
    assert "no data" in res.evidence["trace_absent_reason"]
    assert res.recording.completeness == 0.0
