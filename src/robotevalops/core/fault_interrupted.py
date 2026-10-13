"""F10_interrupted_runner: a runner that dies mid-trial must leave evidence preserved, never a success, and
force a fresh preflight before anything runs again. Uses only a tiny in-module fake adapter (no robotics code,
no hardware, no network)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from robotevalops.adapters.base import (
    Action,
    Controller,
    EpisodeResult,
    Observation,
    PreflightCheck,
    PreflightResult,
    RobotAdapter,
    StepResult,
)
from robotevalops.core.runner import Runner
from robotevalops.core.service import EvalService
from robotevalops.errors import PreflightFailedError
from robotevalops.schemas import (
    ConditionSpec,
    ControllerSpec,
    ControllerType,
    EvalConfig,
    FaultResult,
    Provenance,
    QACode,
    RecordingSummary,
    SessionState,
    TaskOutcome,
    TerminationReason,
    TrialState,
)
from robotevalops.util import sha256_file, utcnow


class _NoopController(Controller):
    def __init__(self, spec: ControllerSpec) -> None:
        self.spec = spec

    def reset(self, observation: Observation, seed: int) -> None:
        return None

    def act(self, observation: Observation) -> Action:
        return Action(values=[0.0])


class _FakeAdapter(RobotAdapter):
    """Mock-provenance fake: writes a one-row trace and reports a fixture success. Counts episodes."""

    provenance = Provenance.MOCK
    name = "fault_fake"

    def __init__(self) -> None:
        self.episodes = 0
        self._stop = False

    def preflight(self) -> PreflightResult:
        return PreflightResult([PreflightCheck("fake", True)])

    def reset(self, condition: ConditionSpec, seed: int) -> Observation:
        return Observation(t=0.0, state={})

    def observe(self) -> Observation:
        return Observation(t=0.0, state={})

    def act(self, action: Action) -> None:
        return None

    def step(self) -> StepResult:
        return StepResult(self.observe(), done=True)

    def request_stop(self) -> None:
        self._stop = True

    @property
    def stop_requested(self) -> bool:
        return self._stop

    def start_recording(self, out_dir: Path) -> None:
        return None

    def stop_recording(self) -> RecordingSummary:
        return RecordingSummary()

    def run_episode(
        self, controller: Controller, out_dir: Path, timeout_s: float, dwell_required_s: float
    ) -> EpisodeResult:
        self.episodes += 1
        (out_dir / "trace.jsonl").write_text('{"kind":"header"}\n', encoding="utf-8")
        return EpisodeResult(
            termination_reason=TerminationReason.SUCCESS_CRITERION_MET,
            duration_s=0.1,
            task_success=True,
            evidence={"fixture": True},
            recording=RecordingSummary(trace_relpath="trace.jsonl", trace_rows=1),
        )

    def close(self) -> None:
        return None


def run_interrupted_runner_case(workdir: Path) -> FaultResult:
    workdir = Path(workdir)
    home = workdir / "f10_home"
    cfg = EvalConfig(
        name="f10",
        provenance=Provenance.MOCK,
        backend="mock",
        controllers=[ControllerSpec(controller_id="f10_ctrl", type=ControllerType.SCRIPTED, version="1")],
        conditions=[ConditionSpec(name="nominal", kind="nominal")],
        trials_per_condition=2,
    )
    svc = EvalService(home)
    session = svc.create_session("f10", Provenance.MOCK, "mock", eval_config=cfg)
    sid = session.session_id
    trials = svc.plan_trials(sid, cfg)
    svc.mark_preflight_passed(sid)
    svc.transition_session(sid, SessionState.RUNNING)

    # --- the runner dies mid-trial: trial 0 is RUNNING with partial files and no result recorded
    victim = trials[0]
    for st in (TrialState.PREFLIGHT, TrialState.READY):
        svc.transition_trial(victim.trial_id, st)
    svc.transition_trial(victim.trial_id, TrialState.RUNNING, evidence={"runner": {"note": "pre-crash"}})
    tdir = svc.trial_dir(sid, victim.trial_id)
    tdir.mkdir(parents=True, exist_ok=True)
    partial = tdir / "trace.jsonl"
    partial.write_text('{"kind":"header"}\n{"i":0,"t":0.0,"state":[0.0],"action":[0.0]}\n', encoding="utf-8")
    hash_before = sha256_file(partial)
    del svc  # the process "dies"

    # --- restart: a new service instance on the same database
    svc2 = EvalService(home)
    found = [s.session_id for s in svc2.find_interrupted()]
    recovered = svc2.recover_interrupted(sid)
    again = svc2.recover_interrupted(sid)  # idempotent
    t = svc2.get_trial(victim.trial_id)
    s = svc2.get_session(sid)
    on_disk_hash = sha256_file(partial) if partial.exists() else None
    registered = {a.relpath: a for a in t.artifacts}
    rel = f"trials/{victim.trial_id}/trace.jsonl"

    adapter = _FakeAdapter()
    runner = Runner(svc2, lambda _s: adapter, _NoopController)
    refused = False
    refusal_message = ""
    try:
        runner.run_session(sid)
    except PreflightFailedError as e:
        refused = True
        refusal_message = str(e)
    ran_before_preflight = adapter.episodes

    svc2.mark_preflight_passed(sid)
    runner.run_session(sid)
    t_after = svc2.get_trial(victim.trial_id)
    other = svc2.get_trial(trials[1].trial_id)

    checks: dict[str, bool] = {
        "interrupted_session_found": sid in found,
        "one_running_trial_recovered": [x.trial_id for x in recovered] == [victim.trial_id],
        "recovery_idempotent": again == [],
        "trial_aborted_interrupted_runner": t.state == TrialState.ABORTED
        and t.termination_reason == TerminationReason.INTERRUPTED_RUNNER,
        "trial_not_success": t.task_outcome == TaskOutcome.UNSCORED and not t.is_autonomous_success,
        "partial_file_preserved_unchanged": on_disk_hash == hash_before,
        "partial_file_registered_with_hash": rel in registered and registered[rel].sha256 == hash_before,
        "pre_crash_evidence_kept": t.evidence.get("runner", {}).get("note") == "pre-crash"
        and rel in t.evidence["interrupted_runner"]["files_on_disk"],
        "session_requires_fresh_preflight": s.state == SessionState.PREFLIGHT and s.requires_fresh_preflight,
        "runner_refused_before_preflight": refused and ran_before_preflight == 0,
        "no_auto_resume": t_after.state == TrialState.ABORTED and t_after.started_at == t.started_at,
        "remaining_trial_ran_after_preflight": other.state == TrialState.COMPLETED and adapter.episodes == 1,
    }
    detected = checks["trial_aborted_interrupted_runner"] and checks["session_requires_fresh_preflight"]
    evidence_preserved = (
        checks["partial_file_preserved_unchanged"]
        and checks["partial_file_registered_with_hash"]
        and checks["pre_crash_evidence_kept"]
    )
    prevented = (
        checks["trial_not_success"] and checks["runner_refused_before_preflight"] and checks["no_auto_resume"]
    )
    details: dict[str, Any] = {
        "checks": checks,
        "session_id": sid,
        "trial_id": victim.trial_id,
        "refusal_message": refusal_message,
        "evidence": json.loads(json.dumps(t.evidence, default=str)),
    }
    return FaultResult(
        case_id="F10_interrupted_runner",
        description="Runner process dies while a trial is RUNNING; restart must preserve evidence, never "
        "report success and require a fresh preflight before any further trial.",
        expected_code=QACode.INTERRUPTED_RUNNER,
        detected=detected and all(checks.values()),
        detected_codes=[QACode.INTERRUPTED_RUNNER.value] if detected else [],
        message=(
            f"trial {victim.trial_id} marked aborted/{t.termination_reason.value}; session requires a fresh "
            f"preflight. Runner said: {refusal_message}"
        ),
        evidence_preserved=evidence_preserved,
        misleading_success_prevented=prevented,
        executed_at=utcnow(),
        details=details,
    )
