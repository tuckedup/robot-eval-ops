"""Audit A6: standalone hardware commands must use unique durable sessions and the SAME physical-port lease as
`session run`, including when two configs are different aliases of one serial port. Fake executables only."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest
from robotics_helpers import make_calibration, make_cfg
from typer.testing import CliRunner

import robotevalops.cli.robot_cmds as rc
from robotevalops.adapters.hardware_so101 import SO101HardwareAdapter
from robotevalops.core.devices import canonical_port, hardware_lock_keys
from robotevalops.core.runner import Runner
from robotevalops.core.service import EvalService
from robotevalops.errors import DeviceBusyError
from robotevalops.schemas import Provenance, SessionState

runner = CliRunner()

WAITER = """
import json, sys, time, os
from pathlib import Path
log, release = sys.argv[1], sys.argv[2]
Path(log).write_text(json.dumps(sys.argv[3:]), encoding="utf-8")
Path(log + ".started").write_text("1")
deadline = time.time() + 40
while not Path(release).exists() and time.time() < deadline:
    time.sleep(0.05)
sys.exit(0 if Path(release).exists() else 5)
"""

QUICK = "import sys; open(sys.argv[1], 'w').write('ran'); sys.exit(int(sys.argv[2]))"


def _yaml(path: Path, cfg_follower: str, leader: str, fid: str, lid: str) -> Path:
    path.write_text(
        f"follower_id: {fid}\nfollower_port: {cfg_follower}\nleader_id: {lid}\nleader_port: {leader}\n"
        "cameras:\n  front: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def lab(tmp_path, monkeypatch):
    """Two config files that name the SAME two serial ports with different spelling and different ids."""
    cal = tmp_path / "calib"
    monkeypatch.setenv("HF_LEROBOT_CALIBRATION", str(cal))
    home = tmp_path / "home"
    monkeypatch.setenv("ROBOTEVALOPS_HOME", str(home))
    cfg_a = _yaml(tmp_path / "a.yaml", "COM3", "COM4", "fol_a", "lead_a")
    cfg_b = _yaml(tmp_path / "b.yaml", "COM3", "COM5", "fol_b", "lead_b")  # same follower port, other ids
    for kw in (
        {"follower_id": "fol_a", "leader_id": "lead_a"},
        {"follower_id": "fol_b", "leader_id": "lead_b"},
    ):
        make_calibration(cal, make_cfg(**kw))
    waiter = tmp_path / "waiter.py"
    waiter.write_text(WAITER, encoding="utf-8")
    quick = tmp_path / "quick.py"
    quick.write_text(QUICK, encoding="utf-8")
    release = tmp_path / "release"

    def use(script: Path, *args: str):
        ov = {t: [sys.executable, str(script), *args] for t in ("lerobot-record", "lerobot-teleoperate")}
        real = SO101HardwareAdapter

        def factory(cfg, **kw):
            kw.update(
                overrides=ov,
                port_lister=lambda: {"COM3", "COM4", "COM5", "com3"},
                camera_probe=lambda c: (True, "FAKE"),
            )
            return real(cfg, **kw)

        monkeypatch.setattr(rc, "SO101HardwareAdapter", factory)

    return {
        "a": cfg_a,
        "b": cfg_b,
        "home": home,
        "use": use,
        "release": release,
        "tmp": tmp_path,
        "waiter": waiter,
        "quick": quick,
    }


def _cmd(kind, cfg, home, extra=()):
    return runner.invoke(
        rc.app,
        [
            kind,
            "--config",
            str(cfg),
            "--hardware-mode",
            "--ack-operator",
            "alice",
            "--home",
            str(home),
            "--timeout",
            "60",
            "--json",
            *extra,
        ],
    )


def test_port_keys_are_canonical():
    assert canonical_port("COM3") == canonical_port("com3") == canonical_port(r"\\.\COM3")
    assert hardware_lock_keys(["COM3", "com3", "COM4"]) == ["port:COM3", "port:COM4"]
    assert hardware_lock_keys(["COM3"], label="bench") == ["label:bench", "port:COM3"]


def test_command_creates_unique_durable_session_and_releases_lease(lab):
    lab["use"](lab["quick"], str(lab["tmp"] / "ran.txt"), "0")
    r1 = _cmd("record", lab["a"], lab["home"])
    r2 = _cmd("record", lab["a"], lab["home"])
    assert r1.exit_code == 0 and r2.exit_code == 0, (r1.stdout, r2.stdout)
    s1, s2 = json.loads(r1.stdout)["session_id"], json.loads(r2.stdout)["session_id"]
    assert s1 != s2 and "cli-session" not in (s1, s2)
    svc = EvalService(lab["home"])
    for sid in (s1, s2):
        rec = svc.get_session(sid)
        assert rec.provenance == Provenance.PHYSICAL_HARDWARE and rec.state == SessionState.COMPLETED
        assert rec.operator == "alice" and rec.operator_ack_at is not None
        kinds = [e["kind"] for e in svc.list_events(sid)]
        assert {
            "device_acquired",
            "hardware_command_start",
            "hardware_command_end",
            "device_released",
        } <= set(kinds)
        assert (svc.run_dir(sid) / "hardware_command.json").is_file()
    assert svc.device_lock_holder("port:COM3") is None  # nothing left held


def test_failed_command_marks_session_failed_and_still_releases(lab):
    lab["use"](lab["quick"], str(lab["tmp"] / "ran.txt"), "3")
    r = _cmd("teleop", lab["a"], lab["home"])
    assert r.exit_code == 1, r.stdout
    svc = EvalService(lab["home"])
    (s,) = svc.list_sessions()
    assert s.state == SessionState.FAILED and svc.device_lock_holder("port:COM3") is None, (s.notes, r.stdout)


def test_concurrent_command_on_aliased_port_is_refused_while_first_runs(lab):
    lab["use"](lab["waiter"], str(lab["tmp"] / "argv.json"), str(lab["release"]))
    results: dict[str, object] = {}
    t = threading.Thread(target=lambda: results.setdefault("first", _cmd("record", lab["a"], lab["home"])))
    t.start()
    try:
        started = lab["tmp"] / "argv.json.started"
        for _ in range(400):
            if started.exists():
                break
            time.sleep(0.05)
        assert started.exists(), "first fake process never started"
        svc = EvalService(lab["home"])
        holder = svc.device_lock_holder("port:COM3")
        assert holder is not None
        # different config file, ids and leader port; same follower COM3
        second = _cmd("teleop", lab["b"], lab["home"])
        assert second.exit_code == 2, second.stdout
        assert "locked by session" in second.stdout and holder in second.stdout
        sessions = svc.list_sessions()
        assert len(sessions) == 2
        refused = next(s for s in sessions if s.session_id != holder)
        assert refused.state == SessionState.ABORTED and "refused" in refused.notes
        assert not any(e["kind"] == "hardware_command_start" for e in svc.list_events(refused.session_id))
    finally:
        lab["release"].write_text("go")
        t.join(timeout=60)
    assert results["first"].exit_code == 0
    svc = EvalService(lab["home"])
    assert svc.device_lock_holder("port:COM3") is None
    third = _cmd("teleop", lab["b"], lab["home"])  # lease free again
    assert third.exit_code == 0, third.stdout


def test_session_run_runner_collides_with_standalone_command(lab):
    """`session run` (Runner) uses the same port keys: a held CLI lease makes the Runner refuse."""
    from robotevalops.adapters.registry import device_lease_keys

    svc = EvalService(lab["home"])
    cli = svc.create_session("cli", Provenance.PHYSICAL_HARDWARE, "so101_lerobot")
    svc.acquire_devices(hardware_lock_keys(["COM3", "COM4"]), cli.session_id)
    other = svc.create_session("other", Provenance.PHYSICAL_HARDWARE, "so101_lerobot", device_id="some-label")
    svc.acknowledge_operator(other.session_id, "bob")
    svc.mark_preflight_passed(other.session_id)

    class S:  # session-like with the so101 backend
        backend = "so101_lerobot"

    import os

    os.environ["ROBOTEVALOPS_SO101_CONFIG"] = str(lab["b"])  # alias spelling com3 / com5
    try:
        keys = device_lease_keys(S())
    finally:
        del os.environ["ROBOTEVALOPS_SO101_CONFIG"]
    assert keys == ["port:COM3", "port:COM5"]
    r = Runner(
        svc,
        lambda s: (_ for _ in ()).throw(AssertionError("adapter must not be built")),
        lambda spec: None,
        device_keys=lambda s: keys,
    )
    with pytest.raises(DeviceBusyError, match=cli.session_id):
        r.run_session(other.session_id)
    assert svc.get_session(other.session_id).state == SessionState.READY  # untouched, no half-held lease
    assert svc.device_lock_holder("port:COM5") is None


def test_acquire_devices_is_all_or_nothing(tmp_path):
    svc = EvalService(tmp_path)
    a = svc.create_session("a", Provenance.PHYSICAL_HARDWARE, "so101_lerobot")
    b = svc.create_session("b", Provenance.PHYSICAL_HARDWARE, "so101_lerobot")
    svc.acquire_devices(["port:COM4"], a.session_id)
    with pytest.raises(DeviceBusyError):
        svc.acquire_devices(["port:COM3", "port:COM4"], b.session_id)
    assert svc.device_lock_holder("port:COM3") is None  # COM3 not left half-acquired by b
    svc.acquire_devices(["port:COM4", "port:COM9"], a.session_id)  # re-acquire by owner is idempotent


def test_interrupted_command_aborts_session_and_frees_lease(lab, monkeypatch):
    lab["use"](lab["quick"], str(lab["tmp"] / "ran.txt"), "0")
    real = rc.SO101HardwareAdapter

    def factory(cfg, **kw):
        ad = real(cfg, **kw)

        def boom(*_a, **_k):
            raise KeyboardInterrupt

        monkeypatch.setattr(ad.wrapper, "run", boom)
        return ad

    monkeypatch.setattr(rc, "SO101HardwareAdapter", factory)
    r = _cmd("record", lab["a"], lab["home"])
    assert r.exit_code != 0
    svc = EvalService(lab["home"])
    (s,) = svc.list_sessions()
    assert s.state == SessionState.ABORTED and "interrupted" in s.notes
    assert svc.device_lock_holder("port:COM3") is None
