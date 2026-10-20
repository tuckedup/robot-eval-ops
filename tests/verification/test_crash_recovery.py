# ruff: noqa: E501, B023
"""V3: kill a real runner process mid-trial (TerminateProcess, no cleanup) and verify recovery semantics."""

from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from robotevalops.adapters.mock import MockAdapter
from robotevalops.controllers.mock_scripted import MockScriptedController
from robotevalops.core.runner import Runner
from robotevalops.core.service import EvalService
from robotevalops.errors import HardwareRefusedError, PreflightFailedError
from robotevalops.schemas import (
    ConditionSpec,
    ControllerSpec,
    ControllerType,
    EvalConfig,
    Provenance,
    SessionState,
    TaskOutcome,
    TerminationReason,
    TrialState,
)

CHILD = textwrap.dedent(
    """
    import sys
    from robotevalops.adapters.mock import MockAdapter
    from robotevalops.controllers.mock_scripted import MockScriptedController
    from robotevalops.core.runner import Runner
    from robotevalops.core.service import EvalService

    home, sid = sys.argv[1], sys.argv[2]
    svc = EvalService(home)
    Runner(svc, lambda s: MockAdapter(faults={"hang_until_stop"}, max_hang_s=120),
           lambda spec: MockScriptedController(spec)).run_session(sid)
    """
)


def _cfg() -> EvalConfig:
    return EvalConfig(
        name="crash",
        provenance=Provenance.MOCK,
        backend="mock",
        controllers=[ControllerSpec(controller_id="c", type=ControllerType.SCRIPTED, version="1")],
        conditions=[ConditionSpec(name="k", kind="nominal")],
        trials_per_condition=3,
        base_seed=1,
    )


def _spawn_and_kill(home: Path, sid: str, svc: EvalService) -> None:
    script = home.parent / "child.py"
    script.write_text(CHILD, encoding="utf-8")
    popen_kw = {"start_new_session": True} if os.name != "nt" else {}
    p = subprocess.Popen([sys.executable, str(script), str(home), sid], **popen_kw)
    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            running = svc.list_trials(sid, TrialState.RUNNING)
            if running and (svc.trial_dir(sid, running[0].trial_id) / "trace.jsonl").exists():
                time.sleep(1.0)  # let some rows/frames hit disk
                break
            time.sleep(0.1)
        else:
            pytest.fail("child never reached RUNNING")
    finally:
        if os.name == "nt":
            # The recorder starts ffmpeg as a child. Kill descendants too so an encoder cannot
            # finalize video.mp4 after the recovery test has captured its crash-state bytes.
            subprocess.run(
                ["taskkill", "/PID", str(p.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if p.poll() is None:
                p.kill()
        else:
            os.killpg(p.pid, signal.SIGKILL)
        p.wait(timeout=20)


def _digest(d: Path) -> dict[str, str]:
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(d.iterdir()) if f.is_file()}


def test_kill_mid_trial_then_recover(tmp_path: Path) -> None:
    home = tmp_path / "home"
    svc = EvalService(home)
    cfg = _cfg()
    s = svc.create_session("crash", Provenance.MOCK, "mock", eval_config=cfg)
    svc.plan_trials(s.session_id, cfg)
    sid = s.session_id
    _spawn_and_kill(home, sid, svc)

    # --- a brand new service (new process-equivalent) sees the wreckage
    svc2 = EvalService(home)
    assert svc2.get_session(sid).state == SessionState.RUNNING
    assert [x.session_id for x in svc2.find_interrupted()] == [sid]
    running = svc2.list_trials(sid, TrialState.RUNNING)
    assert len(running) == 1
    tid = running[0].trial_id
    before = _digest(svc2.trial_dir(sid, tid))
    assert "trace.jsonl" in before

    # Runner must refuse a still-RUNNING (unrecovered) session
    runner = Runner(svc2, lambda s_: MockAdapter(), lambda spec: MockScriptedController(spec))
    with pytest.raises(PreflightFailedError):
        runner.run_session(sid)

    recovered = svc2.recover_interrupted(sid)
    assert [t.trial_id for t in recovered] == [tid]
    t = svc2.get_trial(tid)
    assert (t.state, t.termination_reason) == (TrialState.ABORTED, TerminationReason.INTERRUPTED_RUNNER)
    assert t.task_outcome == TaskOutcome.UNSCORED and t.duration_s is None
    assert "interrupted_runner" in t.evidence
    assert _digest(svc2.trial_dir(sid, tid)) == before  # evidence bytes untouched by recovery
    assert {a.relpath.rsplit("/", 1)[-1] for a in t.artifacts} >= {"trace.jsonl"}
    sess = svc2.get_session(sid)
    assert sess.state == SessionState.PREFLIGHT and sess.requires_fresh_preflight is True

    # idempotent
    assert svc2.recover_interrupted(sid) == []
    assert svc2.find_interrupted() == []

    # Runner refuses until a fresh preflight is recorded; planned trials are NOT silently run
    with pytest.raises(PreflightFailedError):
        runner.run_session(sid)
    assert all(x.state == TrialState.PLANNED for x in svc2.list_trials(sid, TrialState.PLANNED))
    assert len(svc2.list_trials(sid, TrialState.PLANNED)) == 2

    svc2.mark_preflight_passed(sid)
    rep = runner.run_session(sid, max_trials=1)
    assert tid not in rep.trials_processed  # the interrupted trial is never auto-resumed or re-run
    assert svc2.get_trial(tid).state == TrialState.ABORTED


def test_kill_physical_session_releases_lock_only_on_recovery_and_needs_ack_again(tmp_path: Path) -> None:
    """Uses a MOCK adapter inside a session declared physical_hardware purely to exercise Runner gating."""
    home = tmp_path / "home"
    svc = EvalService(home)
    cfg = EvalConfig(
        name="hw-crash",
        provenance=Provenance.PHYSICAL_HARDWARE,
        backend="so101_lerobot",
        controllers=[ControllerSpec(controller_id="t", type=ControllerType.TELEOPERATED, version="1")],
        conditions=[ConditionSpec(name="k", kind="nominal")],
        trials_per_condition=2,
    )
    s = svc.create_session(
        "hw", Provenance.PHYSICAL_HARDWARE, "so101_lerobot", eval_config=cfg, device_id="so101-test"
    )
    svc.plan_trials(s.session_id, cfg)
    sid = s.session_id
    runner = Runner(svc, lambda s_: MockAdapter(), lambda spec: MockScriptedController(spec))
    with pytest.raises(HardwareRefusedError):  # no ack
        runner.run_session(sid)
    svc.acknowledge_operator(sid, "tester")
    with pytest.raises(PreflightFailedError):  # ack but no preflight
        runner.run_session(sid)
    svc.mark_preflight_passed(sid)

    _spawn_and_kill(home, sid, svc)
    svc2 = EvalService(home)
    assert svc2.device_lock_holder("so101-test") == sid  # stale lock after the crash (fail-safe)
    svc2.recover_interrupted(sid)
    assert svc2.device_lock_holder("so101-test") is None
    r2 = Runner(svc2, lambda s_: MockAdapter(), lambda spec: MockScriptedController(spec))
    with pytest.raises(PreflightFailedError):
        r2.run_session(sid)
    for st in svc2.list_trials(sid):
        assert st.task_outcome == TaskOutcome.UNSCORED
