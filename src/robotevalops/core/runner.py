"""Runner: the ONLY component that calls adapters. Owns the device lock, the per-trial lifecycle and the
persisted-stop-request watcher.

Per trial: planned -> preflight -> ready -> (reset) -> running -> run_episode -> completed|failed|aborted.
Rules enforced here (see docs/architecture.md):
  * refuse to run when the session requires a fresh preflight (PreflightFailedError);
  * physical sessions additionally need operator_ack_at (HardwareRefusedError) and an explicit READY state;
  * a failed infra/recording trial or a raised exception is FAILED and stays UNSCORED (never success);
  * a stop request (persisted) is forwarded to adapter.request_stop(); once seen, no new trial starts;
  * after a crash nothing resumes: see core/recovery.py.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from robotevalops.adapters.base import Controller, EpisodeResult, RobotAdapter
from robotevalops.core.files import describe_file, missing_ref, scan_dir
from robotevalops.core.service import EvalService
from robotevalops.errors import HardwareRefusedError, NotFoundError, PreflightFailedError
from robotevalops.schemas import (
    ArtifactRef,
    ArtifactRole,
    ConditionSpec,
    ControllerSpec,
    Intervention,
    Provenance,
    QAReport,
    ScoreSource,
    SessionRecord,
    SessionState,
    TaskOutcome,
    TerminationReason,
    TrialRecord,
    TrialState,
)
from robotevalops.util import atomic_write_text, canonical_json, get_logger, utcnow

_ABORT_REASONS = frozenset(
    {
        TerminationReason.OPERATOR_ABORT,
        TerminationReason.SOFTWARE_STOP_REQUEST,
        TerminationReason.SAFETY_STOP,
    }
)

QAHook = Callable[[TrialRecord, Path], QAReport]
ManifestHook = Callable[[str], Any]


@dataclass
class RunReport:
    session_id: str
    final_session_state: SessionState
    trials_processed: list[str] = field(default_factory=list)
    stopped: bool = False
    halted_reason: str | None = None


class Runner:
    def __init__(
        self,
        service: EvalService,
        adapter_factory: Callable[[SessionRecord], RobotAdapter],
        controller_factory: Callable[[ControllerSpec], Controller],
        condition_lookup: Callable[[str], ConditionSpec] | None = None,
        qa_hook: QAHook | None = None,
        manifest_hook: ManifestHook | None = None,
        logger: logging.Logger | None = None,
        *,
        stop_poll_interval_s: float = 0.05,
    ) -> None:
        self.service = service
        self.adapter_factory = adapter_factory
        self.controller_factory = controller_factory
        self.condition_lookup = condition_lookup
        self.qa_hook = qa_hook
        self.manifest_hook = manifest_hook
        self._logger = logger
        self.stop_poll_interval_s = stop_poll_interval_s

    # ------------------------------------------------------------------ public
    def run_session(self, session_id: str, max_trials: int | None = None) -> RunReport:
        svc = self.service
        session = svc.get_session(session_id)
        self._gate(session)
        eval_config = svc.get_eval_config(session_id)
        controllers = {c.controller_id: c for c in eval_config.controllers} if eval_config else {}
        conditions = {c.name: c for c in eval_config.conditions} if eval_config else {}

        own_logger = self._logger is None
        log = self._logger or get_logger(
            f"robotevalops.runner.{session_id}", svc.run_dir(session_id) / "session.log.jsonl"
        )
        device_key = (session.device_id or session.backend) if self._is_physical(session) else None
        locked = False
        adapter: RobotAdapter | None = None
        watcher_done = threading.Event()
        watcher: threading.Thread | None = None
        report = RunReport(session_id, session.state)
        try:
            if device_key is not None:
                svc.acquire_device(device_key, session_id)
                locked = True
            if session.state in (SessionState.PLANNED, SessionState.PREFLIGHT):
                # mock/simulation only (physical needs READY, enforced in _gate); every trial still runs
                # adapter.preflight() before it starts.
                svc.mark_preflight_passed(session_id)
            adapter = self.adapter_factory(session)
            svc.transition_session(session_id, SessionState.RUNNING)
            watcher = threading.Thread(
                target=self._watch_stop,
                args=(session_id, adapter, watcher_done),
                daemon=True,
                name="stop-watcher",
            )
            watcher.start()
            self._loop(session, adapter, controllers, conditions, max_trials, report, log)
            self._finish_session(session, report)
        finally:
            watcher_done.set()
            if watcher is not None:
                watcher.join(timeout=5)
            if adapter is not None:
                try:
                    adapter.close()
                except Exception:  # noqa: BLE001 - closing must not mask the real error
                    log.exception("adapter.close failed")
            if locked and device_key is not None:
                svc.release_device(device_key, session_id)
            if own_logger:
                for h in list(log.handlers):
                    if getattr(h, "_roe_file", None):
                        log.removeHandler(h)
                        h.close()
        if self.manifest_hook is not None:
            self._safe_hook(
                "manifest_hook",
                lambda: self.manifest_hook(session_id) if self.manifest_hook else None,
                session_id,
                None,
                log,
            )
        return report

    # ------------------------------------------------------------------ gating
    @staticmethod
    def _is_physical(session: SessionRecord) -> bool:
        return session.provenance == Provenance.PHYSICAL_HARDWARE

    def _gate(self, session: SessionRecord) -> None:
        if session.state in (SessionState.COMPLETED, SessionState.FAILED, SessionState.ABORTED):
            raise PreflightFailedError(
                f"session {session.session_id} is {session.state.value}; nothing to run"
            )
        if self._is_physical(session) and session.operator_ack_at is None:
            raise HardwareRefusedError(
                f"session {session.session_id} is physical_hardware and has no operator acknowledgement; run "
                f"`robotevalops session ack {session.session_id} --operator <name>` after checking the cell"
            )
        if session.requires_fresh_preflight:
            raise PreflightFailedError(
                f"session {session.session_id} requires a fresh preflight (set after an interruption or halt); "  # noqa: E501
                f"run `robotevalops session preflight {session.session_id}` before running trials"
            )
        if session.state == SessionState.RUNNING:
            raise PreflightFailedError(
                f"session {session.session_id} is already RUNNING (another runner, or a crash); run "
                f"`robotevalops session recover {session.session_id}` and preflight first"
            )
        if self._is_physical(session) and session.state != SessionState.READY:
            raise PreflightFailedError(
                f"physical session {session.session_id} is {session.state.value}; run a passing preflight first"  # noqa: E501
            )

    # ------------------------------------------------------------------ stop watcher
    def _watch_stop(self, session_id: str, adapter: RobotAdapter, done: threading.Event) -> None:
        while not done.wait(self.stop_poll_interval_s):
            try:
                if self.service.is_stop_requested(session_id):
                    adapter.request_stop()
                    return
            except Exception:  # noqa: BLE001 - keep polling; the loop-top check is the backstop
                continue

    # ------------------------------------------------------------------ main loop
    def _loop(
        self,
        session: SessionRecord,
        adapter: RobotAdapter,
        controllers: dict[str, ControllerSpec],
        conditions: dict[str, ConditionSpec],
        max_trials: int | None,
        report: RunReport,
        log: logging.Logger,
    ) -> None:
        svc = self.service
        sid = session.session_id
        started = 0
        for trial in svc.list_trials(sid):
            if trial.state in (TrialState.COMPLETED, TrialState.FAILED, TrialState.ABORTED):
                continue  # terminal trials are never re-run (no auto-resume)
            if svc.is_stop_requested(sid):
                adapter.request_stop()
                report.stopped = True
                report.halted_reason = "stop_requested"
                return
            if max_trials is not None and started >= max_trials:
                return
            started += 1
            report.trials_processed.append(trial.trial_id)
            halt = self._run_trial(session, adapter, trial, controllers, conditions, log)
            if halt is not None:
                report.halted_reason = halt
                report.stopped = halt in ("aborted", "stop_requested")
                return

    def _condition(self, name: str, conditions: dict[str, ConditionSpec]) -> ConditionSpec:
        if self.condition_lookup is not None:
            return self.condition_lookup(name)
        if name in conditions:
            return conditions[name]
        raise NotFoundError(
            f"condition {name!r} not found (no condition_lookup and not in the stored eval config)"
        )

    def _controller_spec(self, trial: TrialRecord, controllers: dict[str, ControllerSpec]) -> ControllerSpec:
        spec = controllers.get(trial.controller_id)
        if spec is None:
            raise NotFoundError(
                f"controller {trial.controller_id!r} not found in the session's stored eval config"
            )
        if spec.config_hash != trial.controller_config_hash:
            raise NotFoundError(
                f"controller {trial.controller_id!r} config hash differs from the planned trial; refusing to run"  # noqa: E501
            )
        return spec

    def _run_trial(
        self,
        session: SessionRecord,
        adapter: RobotAdapter,
        trial: TrialRecord,
        controllers: dict[str, ControllerSpec],
        conditions: dict[str, ConditionSpec],
        log: logging.Logger,
    ) -> str | None:
        """Run one trial. Returns None to continue, or a halt reason ('preflight_failed', 'aborted', ...)."""
        svc = self.service
        sid, tid = session.session_id, trial.trial_id
        physical = self._is_physical(session)
        run_dir = svc.run_dir(sid)
        tdir = svc.trial_dir(sid, tid)

        # ---- preflight (non-moving)
        if trial.state == TrialState.READY or trial.state == TrialState.PLANNED:
            svc.transition_trial(tid, TrialState.PREFLIGHT)
        failures: list[str] = []
        try:
            pf = adapter.preflight()
            if not pf.ok:
                failures = [f"{c.name}: {c.detail}" for c in pf.failures()] or [
                    "no preflight checks reported"
                ]
        except Exception as e:  # noqa: BLE001
            failures = [f"preflight raised {type(e).__name__}: {e}"]
        if failures:
            svc.transition_trial(
                tid,
                TrialState.FAILED,
                termination_reason=TerminationReason.PREFLIGHT_FAILED,
                evidence={"preflight_failures": failures},
            )
            log.error("preflight failed", extra={"fields": {"trial_id": tid, "failures": failures}})
            self._set_session_preflight(sid)
            return "preflight_failed"
        svc.transition_trial(tid, TrialState.READY)

        # ---- build controller + condition BEFORE motion; failures here are infra failures
        try:
            spec = self._controller_spec(trial, controllers)
            condition = self._condition(trial.condition_name, conditions)
            controller = self.controller_factory(spec)
        except Exception as e:  # noqa: BLE001
            return self._fail_before_run(
                session, trial, f"setup failed: {type(e).__name__}: {e}", log, physical
            )

        # ---- reset
        t_reset = time.monotonic()
        reset_error: str | None = None
        try:
            adapter.reset(condition, trial.seed)
        except HardwareRefusedError:
            # A gate refusal is not an attempt: nothing moved. Put the trial back to PREFLIGHT (it never
            # reached RUNNING, so started_at stays unset), pause the session at READY and refuse the run.
            svc.transition_trial(tid, TrialState.PREFLIGHT)
            svc.transition_session(sid, SessionState.READY, note="hardware gate refused motion")
            svc.record_event("hardware_refused", sid, tid, stage="reset")
            raise
        except Exception as e:  # noqa: BLE001
            reset_error = f"reset failed: {type(e).__name__}: {e}"
        reset_duration = time.monotonic() - t_reset

        # ---- running
        tdir.mkdir(parents=True, exist_ok=True)
        svc.transition_trial(
            tid,
            TrialState.RUNNING,
            reset_duration_s=reset_duration,
            evidence={
                "runner": {"pid": os.getpid(), "host": socket.gethostname(), "started": utcnow().isoformat()}
            },
        )
        if reset_error is not None:
            return self._finish_failed(
                session,
                trial,
                TerminationReason.INFRA_FAILURE,
                {"error": reset_error},
                time.monotonic(),
                run_dir,
                tdir,
                None,
                log,
                physical,
                adapter,
            )
        atomic_write_text(
            tdir / "controller.json",
            canonical_json({"spec": spec.model_dump(mode="json"), "config_hash": spec.config_hash}),
        )

        t0 = time.monotonic()
        try:
            result = adapter.run_episode(
                controller, tdir, session.task.attempt_timeout_s, session.task.dwell_required_s
            )
        except Exception as e:  # noqa: BLE001
            log.exception("run_episode raised")
            return self._finish_failed(
                session,
                trial,
                TerminationReason.INFRA_FAILURE,
                {"exception": f"{type(e).__name__}: {e}"},
                t0,
                run_dir,
                tdir,
                None,
                log,
                physical,
                adapter,
            )
        duration = result.duration_s if result.duration_s is not None else time.monotonic() - t0
        return self._finish_ok(session, trial, result, duration, run_dir, tdir, log, physical, adapter)

    # ------------------------------------------------------------------ outcomes
    def _fail_before_run(
        self, session: SessionRecord, trial: TrialRecord, message: str, log: logging.Logger, physical: bool
    ) -> str | None:
        # READY -> FAILED is not allowed; go through RUNNING so the attempt is counted truthfully.
        self.service.transition_trial(trial.trial_id, TrialState.RUNNING)
        self.service.transition_trial(
            trial.trial_id,
            TrialState.FAILED,
            termination_reason=TerminationReason.INFRA_FAILURE,
            evidence={"error": message},
        )
        log.error(message, extra={"fields": {"trial_id": trial.trial_id}})
        return self._halt_if_physical(session, physical)

    def _artifacts(self, run_dir: Path, tdir: Path, result: EpisodeResult | None) -> list[ArtifactRef]:
        refs = {a.relpath: a for a in scan_dir(run_dir, tdir)}
        if result is not None:
            expected = [
                (result.recording.video_relpath, ArtifactRole.VIDEO),
                (result.recording.trace_relpath, ArtifactRole.TRACE),
            ]
            for rel, role in expected:
                if rel:
                    full = tdir / rel
                    if full.is_file():
                        refs[(full.resolve().relative_to(run_dir.resolve())).as_posix()] = describe_file(
                            run_dir, full, role
                        )
                    else:
                        key = (tdir.relative_to(run_dir) / rel).as_posix()
                        refs[key] = missing_ref(key, role, "reported by the adapter but not found on disk")
        return list(refs.values())

    def _finish_failed(
        self,
        session: SessionRecord,
        trial: TrialRecord,
        reason: TerminationReason,
        evidence: dict[str, Any],
        t0: float,
        run_dir: Path,
        tdir: Path,
        result: EpisodeResult | None,
        log: logging.Logger,
        physical: bool,
        adapter: RobotAdapter,
    ) -> str | None:
        if physical:
            try:
                adapter.request_stop()  # best effort; software stop only, NOT an emergency stop
            except Exception:  # noqa: BLE001
                log.exception("adapter.request_stop failed after error")
        rec = self.service.record_trial_result(
            trial.trial_id,
            termination_reason=reason,
            duration_s=time.monotonic() - t0,
            evidence=evidence,
            artifacts=self._artifacts(run_dir, tdir, result),
            intervention=Intervention.UNKNOWN,
        )
        self._run_qa(rec, run_dir, log)
        return self._halt_if_physical(session, physical)

    def _halt_if_physical(self, session: SessionRecord, physical: bool) -> str | None:
        if physical:
            self._set_session_preflight(session.session_id)
            return "infra_failure"
        return None

    def _set_session_preflight(self, session_id: str) -> None:
        """Halt: back to PREFLIGHT with a fresh preflight required (RUNNING -> PREFLIGHT sets the flag)."""
        s = self.service.get_session(session_id)
        if s.state == SessionState.RUNNING:
            self.service.transition_session(session_id, SessionState.PREFLIGHT, note="runner halted")
        self.service.flag_fresh_preflight(session_id)

    def _finish_ok(
        self,
        session: SessionRecord,
        trial: TrialRecord,
        result: EpisodeResult,
        duration: float,
        run_dir: Path,
        tdir: Path,
        log: logging.Logger,
        physical: bool,
        adapter: RobotAdapter,
    ) -> str | None:
        reason = result.termination_reason
        evidence: dict[str, Any] = {**result.evidence, "recording": result.recording.model_dump(mode="json")}
        if result.error:
            evidence["error"] = result.error
            if reason not in (TerminationReason.INFRA_FAILURE, TerminationReason.RECORDING_FAILURE):
                reason = TerminationReason.INFRA_FAILURE  # an adapter-reported error is never a success
        if reason in (
            TerminationReason.NOT_RUN,
            TerminationReason.PREFLIGHT_FAILED,
            TerminationReason.INTERRUPTED_RUNNER,
        ):
            evidence["adapter_termination_reason"] = reason.value
            reason = TerminationReason.INFRA_FAILURE

        outcome: TaskOutcome | None = None
        source: ScoreSource | None = None
        completed = reason in (TerminationReason.SUCCESS_CRITERION_MET, TerminationReason.TIMEOUT)
        if completed and result.task_success is not None:
            consistent = not (
                (reason == TerminationReason.SUCCESS_CRITERION_MET and result.task_success is False)
                or (reason == TerminationReason.TIMEOUT and result.task_success is True)
            )
            if not consistent:
                evidence["inconsistent_adapter_result"] = (
                    f"termination {reason.value} but task_success={result.task_success}; left unscored"
                )
            elif session.provenance == Provenance.SIMULATION:
                outcome = TaskOutcome.SUCCESS if result.task_success else TaskOutcome.FAILURE
                source = ScoreSource.PHYSICS_EVIDENCE
            elif session.provenance == Provenance.MOCK:
                outcome = TaskOutcome.SUCCESS if result.task_success else TaskOutcome.FAILURE
                source = ScoreSource.MOCK_FIXTURE
            # hardware/imported: never auto-scored; an operator scores from the recording.

        if session.provenance in (Provenance.MOCK, Provenance.SIMULATION):
            intervention = Intervention.ASSISTED if result.intervention_detected else Intervention.NONE
        else:
            intervention = Intervention.ASSISTED if result.intervention_detected else Intervention.UNKNOWN

        rec = self.service.record_trial_result(
            trial.trial_id,
            termination_reason=reason,
            duration_s=duration,
            task_outcome=outcome,
            score_source=source,
            intervention=intervention,
            evidence=evidence,
            artifacts=self._artifacts(run_dir, tdir, result),
        )
        self._run_qa(rec, run_dir, log)
        if rec.state == TrialState.ABORTED and reason in _ABORT_REASONS:
            return "stop_requested" if reason == TerminationReason.SOFTWARE_STOP_REQUEST else "aborted"
        if rec.state == TrialState.FAILED:
            return self._halt_if_physical(session, physical)
        return None

    def _run_qa(self, trial: TrialRecord, run_dir: Path, log: logging.Logger) -> None:
        if self.qa_hook is None:
            return
        hook = self.qa_hook

        def call() -> None:
            report = hook(trial, run_dir)
            self.service.set_recording_quality(
                trial.trial_id, report.quality, [f.code.value for f in report.flags]
            )

        self._safe_hook("qa_hook", call, trial.session_id, trial.trial_id, log)

    def _safe_hook(
        self, name: str, fn: Callable[[], Any], session_id: str, trial_id: str | None, log: logging.Logger
    ) -> None:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - hooks must never corrupt the run record
            log.exception("%s failed", name)
            self.service.record_event(f"{name}_error", session_id, trial_id, error=f"{type(e).__name__}: {e}")

    # ------------------------------------------------------------------ session end
    def _finish_session(self, session: SessionRecord, report: RunReport) -> None:
        svc = self.service
        sid = session.session_id
        current = svc.get_session(sid)
        if current.state != SessionState.RUNNING:
            report.final_session_state = current.state  # already halted back to PREFLIGHT
            return
        remaining = [
            t
            for t in svc.list_trials(sid)
            if t.state not in (TrialState.COMPLETED, TrialState.FAILED, TrialState.ABORTED)
        ]
        if report.stopped or report.halted_reason in ("aborted", "stop_requested"):
            new = SessionState.ABORTED
        elif remaining:
            new = SessionState.READY  # max_trials reached; safe to continue later
        else:
            new = SessionState.COMPLETED
        svc.transition_session(sid, new, note=report.halted_reason or "")
        report.final_session_state = new
