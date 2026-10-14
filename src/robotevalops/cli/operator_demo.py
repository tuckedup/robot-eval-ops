# ruff: noqa: E501
"""`robotevalops demo operator`: the ~90 second operator workflow, every step executed for real (simulation).

preflight -> one verified success -> one genuine physics task failure -> one corrupted recording rejected by QA
-> one interrupted + recovered run -> verified local artifact transfer -> report.

Nothing is faked: the success and the task failure are decided by simulator evidence; the corruption is a real
truncation of a recorded video (in this demo home only); the interruption is a real `kill` of a runner process.
Simulation only (Panda in PyBullet, scripted controllers): this demonstrates the software workflow, not a robot.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from robotevalops.adapters.registry import get_adapter
from robotevalops.cli.demo_cmds import _make_runner
from robotevalops.controllers.base import configs_dir, load_conditions, load_controller_specs
from robotevalops.core.service import EvalService
from robotevalops.integration import apply_transfer_report
from robotevalops.metrics.compute import compute_metrics
from robotevalops.qa.trial_qa import qa_trial
from robotevalops.recording.manifest import write_manifest
from robotevalops.reporting.export import export_summary
from robotevalops.schemas import (
    EvalConfig,
    Provenance,
    RecordingQuality,
    TaskSpec,
    TrialState,
    is_autonomous_success,
)
from robotevalops.storage.local import LocalArtifactStore
from robotevalops.storage.package import upload_run, verify_run
from robotevalops.util import atomic_write_text


def _cfg(name: str, ctrl_ids: list[str], cond_names: list[str], trials: int, seed: int) -> EvalConfig:
    ctrls = {
        c.controller_id: c for c in load_controller_specs(configs_dir() / "controllers" / "sim_scripted.yaml")
    }
    conds = {c.name: c for c in load_conditions(configs_dir() / "conditions" / "sim_stress_conditions.yaml")}
    return EvalConfig(
        name=name,
        task=TaskSpec(task_id="pick_place_block_v1", attempt_timeout_s=30.0, dwell_required_s=2.0),
        provenance=Provenance.SIMULATION,
        backend="pybullet_panda",
        controllers=[ctrls[c] for c in ctrl_ids],
        conditions=[conds[c] for c in cond_names],
        trials_per_condition=trials,
        base_seed=seed,
    )


def _new(svc: EvalService, cfg: EvalConfig) -> str:
    s = svc.create_session(cfg.name, cfg.provenance, cfg.backend, eval_config=cfg, purpose="operator-demo")
    svc.plan_trials(s.session_id, cfg)
    return s.session_id


def run_operator_demo(
    home: Path,
    out: Path,
    success_condition: str = "stress_nominal",
    failure_condition: str = "mass_2.0kg",
    failure_controller: str = "scripted_baseline_b",
) -> dict[str, Any]:
    home.mkdir(parents=True, exist_ok=True)
    svc = EvalService(home)
    steps: list[dict[str, Any]] = []

    def step(name: str, data: dict[str, Any], t0: float) -> None:
        steps.append({"step": name, "seconds": round(time.time() - t0, 2), **data})
        print(f"[{len(steps)}] {name}: {json.dumps(data, default=str)[:300]}", flush=True)

    # 1 preflight
    t0 = time.time()
    pre = get_adapter("pybullet_panda").preflight()
    step("preflight", {"ok": pre.ok, "checks": [{c.name: c.ok} for c in pre.checks]}, t0)
    if not pre.ok:
        raise RuntimeError("preflight failed: " + "; ".join(c.detail for c in pre.failures()))

    # 2 + 3 one session, one verified success, one genuine physics task failure
    t0 = time.time()
    cfg = _cfg(
        "operator-demo-main",
        ["scripted_baseline_a", failure_controller],
        [success_condition, failure_condition],
        1,
        31337,
    )
    sid = _new(svc, cfg)
    _make_runner(svc, "pybullet_panda").run_session(sid)
    trials = svc.list_trials(sid)
    succ = next(
        (t for t in trials if is_autonomous_success(t) and t.condition_name == success_condition), None
    )
    fail = next((t for t in trials if t.task_outcome.value == "failure"), None)
    step(
        "one verified success",
        {
            "trial": succ and succ.trial_id,
            "controller": succ and succ.controller_id,
            "condition": success_condition,
            "sim_duration_s": succ and succ.duration_s,
        },
        t0,
    )
    step(
        "one physics task failure (real simulator evidence)",
        {
            "trial": fail and fail.trial_id,
            "controller": fail and fail.controller_id,
            "condition": fail and fail.condition_name,
            "failed_criteria": fail and fail.evidence.get("failed_criteria"),
            "video": f"runs/{sid}/" + next((a.relpath for a in fail.artifacts if a.role.value == "video"), "")
            if fail
            else None,
        },
        t0,
    )

    # 4 corrupted recording rejected by QA
    t0 = time.time()
    cfg2 = _cfg("operator-demo-corrupt", ["scripted_baseline_a"], [success_condition], 1, 4242)
    sid2 = _new(svc, cfg2)
    _make_runner(svc, "pybullet_panda").run_session(sid2)
    (t2,) = svc.list_trials(sid2)
    assert is_autonomous_success(t2), "precondition: the trial succeeded and its recording passed QA"
    video = svc.run_dir(sid2) / next(a.relpath for a in t2.artifacts if a.role.value == "video")
    raw = video.read_bytes()
    video.write_bytes(raw[: len(raw) // 3])  # truncate the RECORDED video in this demo home
    manifest = svc.export_manifest(sid2)
    entry = next(e for e in manifest.trials if e.trial_id == t2.trial_id)
    rep = qa_trial(svc.run_dir(sid2), entry)
    svc.set_recording_quality(
        t2.trial_id,
        rep.quality,
        [f.code.value for f in rep.flags],
        actor="operator-demo",
        reason="re-validation after the video was truncated",
    )
    t2b = svc.get_trial(t2.trial_id)
    step(
        "corrupt recording rejected",
        {
            "trial": t2.trial_id,
            "task_outcome_still_recorded": t2b.task_outcome.value,
            "recording_quality": t2b.recording_quality.value,
            "counts_as_verified_success": is_autonomous_success(t2b),
            "flags": t2b.qa_flags,
            "reasons": [f.message for f in rep.flags][:2],
        },
        t0,
    )
    assert t2b.recording_quality == RecordingQuality.FAIL and not is_autonomous_success(t2b)

    # 5 interrupted + recovered
    t0 = time.time()
    cfg3 = _cfg("operator-demo-interrupt", ["scripted_baseline_a"], [success_condition], 2, 777)
    sid3 = _new(svc, cfg3)
    proc = subprocess.Popen(
        [sys.executable, "-m", "robotevalops.cli.main", "session", "run", sid3, "--home", str(home)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    killed = False
    for _ in range(600):
        if any(t.state == TrialState.RUNNING for t in svc.list_trials(sid3)):
            time.sleep(1.0)  # let it record some frames
            proc.kill()
            killed = True
            break
        time.sleep(0.1)
    proc.wait()
    recovered = svc.recover_interrupted(sid3)
    after = svc.list_trials(sid3)
    s3 = svc.get_session(sid3)
    step(
        "interrupted run recovered",
        {
            "killed_mid_trial": killed,
            "recovered_trials": [t.trial_id for t in recovered],
            "trial_states": [
                (t.state.value, t.termination_reason.value, t.task_outcome.value) for t in after
            ],
            "session_state": s3.state.value,
            "requires_fresh_preflight": s3.requires_fresh_preflight,
            "any_success_recorded": any(is_autonomous_success(t) for t in after),
        },
        t0,
    )

    # 6 verified local artifact transfer (SHA-256 both ways)
    t0 = time.time()
    store = LocalArtifactStore(home / "store")
    write_manifest(svc.run_dir(sid) / "manifest.json", svc.export_manifest(sid))
    up = upload_run(store, svc.run_dir(sid), sid)
    ver = verify_run(store, svc.run_dir(sid), sid)
    apply_transfer_report(svc, sid, ver)
    step(
        "verified artifact transfer",
        {
            "session": sid,
            "uploaded": len(up.artifacts),
            "statuses": sorted({a.status for a in ver.artifacts}),
            "all_verified": all(a.status == "verified" for a in ver.artifacts),
        },
        t0,
    )

    # 7 report
    t0 = time.time()
    written = export_summary(svc, [sid], out / "report")
    export_summary(svc, [sid2], out / "report_corrupt_recording")
    m = compute_metrics(svc.list_trials(sid2)).overall
    step(
        "report",
        {
            "files": {k: str(v) for k, v in written.items()},
            "corrupt_session_attempted": m.attempted,
            "corrupt_session_evaluable": m.evaluable,
            "corrupt_session_verified_successes": m.autonomous_successes,
            "corrupt_session_raw_task_successes": m.raw_task_successes,
        },
        t0,
    )

    summary = {
        "home": str(home),
        "sessions": {"main": sid, "corrupt": sid2, "interrupted": sid3},
        "steps": steps,
        "scope": "SIMULATION ONLY: Panda arm in PyBullet with scripted controllers. Demonstrates the evaluation workflow; not a robot, not a learned policy.",
    }
    out.mkdir(parents=True, exist_ok=True)
    atomic_write_text(out / "operator-demo-summary.json", json.dumps(summary, indent=2, default=str) + "\n")
    return summary
