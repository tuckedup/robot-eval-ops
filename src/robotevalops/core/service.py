"""EvalService: the single persistence/lifecycle API (docs/contracts.md section 3).

Dashboard, reporting and CLI use ONLY this class. The Runner is the only component that calls adapters.
Provenance (mock/simulation/...) and controller_type (scripted/learned/teleoperated) are stored and exposed
separately; neither is ever derived from the other.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from robotevalops.core.db import (
    Database,
    dumps,
    row_to_edit,
    row_to_session,
    row_to_trial,
)
from robotevalops.core.scheduler import build_schedule
from robotevalops.errors import (
    DeviceBusyError,
    DuplicateIdError,
    InvalidTransitionError,
    NotFoundError,
    ScoreProtectionError,
)
from robotevalops.lifecycle_rules import validate_session_transition, validate_trial_transition
from robotevalops.schemas import (
    ArtifactRef,
    ArtifactStatus,
    EvalConfig,
    Intervention,
    Provenance,
    RecordingQuality,
    RunManifest,
    ScoreEdit,
    ScoreSource,
    SessionRecord,
    SessionState,
    TaskOutcome,
    TaskSpec,
    TerminationReason,
    TrialManifestEntry,
    TrialRecord,
    TrialState,
)
from robotevalops.util import (
    get_home,
    git_commit,
    new_id,
    safe_relpath,
    software_versions,
    utcnow,
)

_COMPLETED_REASONS = frozenset({TerminationReason.SUCCESS_CRITERION_MET, TerminationReason.TIMEOUT})
_FAILED_REASONS = frozenset(
    {
        TerminationReason.PREFLIGHT_FAILED,
        TerminationReason.INFRA_FAILURE,
        TerminationReason.RECORDING_FAILURE,
    }
)
_ABORTED_REASONS = frozenset(
    {
        TerminationReason.OPERATOR_ABORT,
        TerminationReason.SOFTWARE_STOP_REQUEST,
        TerminationReason.SAFETY_STOP,
        TerminationReason.INTERRUPTED_RUNNER,
        TerminationReason.NOT_RUN,  # a planned trial cancelled before it ever ran
    }
)

_TRIAL_FIELDS = frozenset(
    {
        "termination_reason",
        "duration_s",
        "reset_duration_s",
        "started_at",
        "ended_at",
        "evidence",
        "intervention",
        "notes",
    }
)


# Which ScoreSource may label a trial of a given provenance (VF-04). physics_evidence needs simulator state,
# mock_fixture is only the mock backend's fixture rule, imported_label only labels imported recordings;
# a human watching the (rendered or physical) video may score any provenance except imported ones that
# carry their own label source.
ALLOWED_SCORE_SOURCES: dict[Provenance, frozenset[ScoreSource]] = {
    Provenance.MOCK: frozenset({ScoreSource.MOCK_FIXTURE, ScoreSource.OPERATOR_VIDEO}),
    Provenance.SIMULATION: frozenset({ScoreSource.PHYSICS_EVIDENCE, ScoreSource.OPERATOR_VIDEO}),
    Provenance.IMPORTED_REAL_RECORDING: frozenset({ScoreSource.IMPORTED_LABEL, ScoreSource.OPERATOR_VIDEO}),
    Provenance.PHYSICAL_HARDWARE: frozenset({ScoreSource.OPERATOR_VIDEO}),
}


def check_score_source(provenance: Provenance, source: ScoreSource) -> None:
    allowed = ALLOWED_SCORE_SOURCES[provenance]
    if source not in allowed:
        raise ValueError(
            f"score_source {source.value!r} is not valid for a {provenance.value} trial; "
            f"allowed: {sorted(x.value for x in allowed)}"
        )


def state_for_termination(reason: TerminationReason) -> TrialState:
    """Terminal trial state implied by a termination reason (the only mapping the system uses)."""
    if reason in _COMPLETED_REASONS:
        return TrialState.COMPLETED
    if reason in _FAILED_REASONS:
        return TrialState.FAILED
    if reason in _ABORTED_REASONS:
        return TrialState.ABORTED
    raise ValueError(f"termination reason {reason.value!r} does not imply a terminal state")


def _check_termination_matches_state(new_state: TrialState, reason: TerminationReason) -> None:
    allowed = {
        TrialState.COMPLETED: _COMPLETED_REASONS,
        TrialState.FAILED: _FAILED_REASONS,
        TrialState.ABORTED: _ABORTED_REASONS,
    }.get(new_state)
    if allowed is not None and reason not in allowed:
        raise InvalidTransitionError(
            f"termination_reason {reason.value!r} is not valid for a {new_state.value} trial; "
            f"allowed: {sorted(r.value for r in allowed)}"
        )


class EvalService:
    """Persistence + lifecycle service over `<home>/robotevalops.db`. Safe to instantiate many times on the
    same home (e.g. after a runner crash): all state lives in SQLite."""

    def __init__(self, home: str | Path | None = None) -> None:
        self.home = get_home(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.db = Database(self.home / "robotevalops.db")

    # ------------------------------------------------------------------ paths
    def run_dir(self, session_id: str) -> Path:
        return self.home / "runs" / session_id

    def trial_dir(self, session_id: str, trial_id: str) -> Path:
        return self.run_dir(session_id) / "trials" / trial_id

    # ------------------------------------------------------------------ internal helpers
    @staticmethod
    def _event(
        c: sqlite3.Connection,
        kind: str,
        session_id: str | None = None,
        trial_id: str | None = None,
        **detail: Any,
    ) -> None:
        c.execute(
            "INSERT INTO events(at, session_id, trial_id, kind, detail_json) VALUES (?,?,?,?,?)",
            (utcnow().isoformat(), session_id, trial_id, kind, dumps(detail)),
        )

    @staticmethod
    def _session(c: sqlite3.Connection, session_id: str) -> SessionRecord:
        r = c.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if r is None:
            raise NotFoundError(f"session {session_id!r} not found")
        return row_to_session(r)

    @staticmethod
    def _trial(c: sqlite3.Connection, trial_id: str) -> TrialRecord:
        r = c.execute("SELECT * FROM trials WHERE trial_id=?", (trial_id,)).fetchone()
        if r is None:
            raise NotFoundError(f"trial {trial_id!r} not found")
        return row_to_trial(r)

    @staticmethod
    def _touch(c: sqlite3.Connection, session_id: str) -> None:
        c.execute("UPDATE sessions SET updated_at=? WHERE session_id=?", (utcnow().isoformat(), session_id))

    @staticmethod
    def _update_trial(c: sqlite3.Connection, trial_id: str, cols: dict[str, Any]) -> None:
        if not cols:
            return
        sets = ", ".join(f"{k}=?" for k in cols)
        c.execute(f"UPDATE trials SET {sets} WHERE trial_id=?", (*cols.values(), trial_id))

    # ------------------------------------------------------------------ sessions
    def create_session(
        self,
        name: str,
        provenance: Provenance,
        backend: str,
        *,
        task: TaskSpec | None = None,
        purpose: str = "evaluation",
        operator: str = "",
        device_id: str | None = None,
        calibration_ref: str | None = None,
        eval_config: EvalConfig | None = None,
        notes: str = "",
        session_id: str | None = None,
    ) -> SessionRecord:
        if not name.strip():
            raise ValueError("session name must be non-empty")
        if eval_config is not None:
            if eval_config.provenance != provenance or eval_config.backend != backend:
                raise ValueError(
                    f"eval_config provenance/backend ({eval_config.provenance.value}/{eval_config.backend}) "
                    f"must match the session ({provenance.value}/{backend})"
                )
            task = task or eval_config.task
        now = utcnow()
        rec = SessionRecord(
            session_id=session_id or new_id(),
            name=name,
            provenance=provenance,
            backend=backend,
            task=task or TaskSpec(),
            purpose=purpose,
            operator=operator,
            device_id=device_id,
            calibration_ref=calibration_ref,
            eval_config_hash=eval_config.config_hash if eval_config else None,
            software=software_versions(),
            git_commit=git_commit(),
            created_at=now,
            updated_at=now,
            notes=notes,
        )
        try:
            with self.db.tx() as c:
                c.execute(
                    "INSERT INTO sessions(session_id,name,state,provenance,backend,task_json,purpose,operator,"  # noqa: E501
                    "device_id,calibration_ref,eval_config_hash,eval_config_json,software_json,git_commit,"
                    "requires_fresh_preflight,operator_ack_at,created_at,updated_at,notes,schema_version) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,NULL,?,?,?,?)",
                    (
                        rec.session_id,
                        rec.name,
                        rec.state.value,
                        rec.provenance.value,
                        rec.backend,
                        rec.task.model_dump_json(),
                        rec.purpose,
                        rec.operator,
                        rec.device_id,
                        rec.calibration_ref,
                        rec.eval_config_hash,
                        eval_config.model_dump_json() if eval_config else None,
                        dumps(rec.software),
                        rec.git_commit,
                        rec.created_at.isoformat(),
                        rec.updated_at.isoformat(),
                        rec.notes,
                        rec.schema_version,
                    ),
                )
                self._event(c, "session_created", rec.session_id, provenance=rec.provenance.value)
        except sqlite3.IntegrityError as e:
            raise DuplicateIdError(f"session id {rec.session_id!r} already exists") from e
        return rec

    def get_session(self, session_id: str) -> SessionRecord:
        with self.db.read() as c:
            return self._session(c, session_id)

    def list_sessions(self, state: SessionState | None = None) -> list[SessionRecord]:
        with self.db.read() as c:
            if state is None:
                rows = c.execute("SELECT * FROM sessions ORDER BY created_at, session_id").fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM sessions WHERE state=? ORDER BY created_at, session_id", (state.value,)
                ).fetchall()
        return [row_to_session(r) for r in rows]

    def get_eval_config(self, session_id: str) -> EvalConfig | None:
        """The EvalConfig stored with the session (None if the session was created without one)."""
        with self.db.read() as c:
            self._session(c, session_id)
            r = c.execute(
                "SELECT eval_config_json FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()
        return EvalConfig.model_validate_json(r[0]) if r[0] else None

    def transition_session(
        self, session_id: str, new_state: SessionState, *, note: str = ""
    ) -> SessionRecord:
        with self.db.tx() as c:
            s = self._session(c, session_id)
            validate_session_transition(s.state, new_state)
            cols: dict[str, Any] = {"state": new_state.value, "updated_at": utcnow().isoformat()}
            # RUNNING -> PREFLIGHT is the crash-recovery edge: always requires a fresh preflight.
            if s.state == SessionState.RUNNING and new_state == SessionState.PREFLIGHT:
                cols["requires_fresh_preflight"] = 1
            if note:
                cols["notes"] = (s.notes + "\n" + note).strip()
            sets = ", ".join(f"{k}=?" for k in cols)
            c.execute(f"UPDATE sessions SET {sets} WHERE session_id=?", (*cols.values(), session_id))
            self._event(
                c, "session_transition", session_id, old=s.state.value, new=new_state.value, note=note
            )
            return self._session(c, session_id)

    def mark_preflight_passed(self, session_id: str) -> SessionRecord:
        """Record a passing preflight: clears requires_fresh_preflight and moves the session to READY."""
        with self.db.tx() as c:
            s = self._session(c, session_id)
            if s.state in (SessionState.PLANNED, SessionState.PREFLIGHT):
                if s.state == SessionState.PLANNED:
                    validate_session_transition(s.state, SessionState.PREFLIGHT)
                validate_session_transition(SessionState.PREFLIGHT, SessionState.READY)
                new_state = SessionState.READY
            elif s.state == SessionState.READY:
                new_state = SessionState.READY
            else:
                raise InvalidTransitionError(
                    f"cannot mark preflight passed for a {s.state.value} session; "
                    "only planned/preflight/ready sessions can be preflighted"
                )
            c.execute(
                "UPDATE sessions SET state=?, requires_fresh_preflight=0, updated_at=? WHERE session_id=?",
                (new_state.value, utcnow().isoformat(), session_id),
            )
            self._event(c, "preflight_passed", session_id, old=s.state.value)
            return self._session(c, session_id)

    def flag_fresh_preflight(self, session_id: str) -> None:
        """Require a fresh preflight before any further trial (set by recovery / runner halts)."""
        with self.db.tx() as c:
            self._session(c, session_id)
            c.execute(
                "UPDATE sessions SET requires_fresh_preflight=1, updated_at=? WHERE session_id=?",
                (utcnow().isoformat(), session_id),
            )
            self._event(c, "fresh_preflight_required", session_id)

    def acknowledge_operator(self, session_id: str, operator: str) -> SessionRecord:
        """Per-session operator acknowledgement (required before any physical-hardware trial)."""
        if not operator.strip():
            raise ValueError("operator name must be non-empty")
        with self.db.tx() as c:
            s = self._session(c, session_id)
            if s.state in (SessionState.COMPLETED, SessionState.FAILED, SessionState.ABORTED):
                raise InvalidTransitionError(f"session is {s.state.value}; acknowledgement not applicable")
            now = utcnow().isoformat()
            c.execute(
                "UPDATE sessions SET operator=?, operator_ack_at=?, updated_at=? WHERE session_id=?",
                (operator, now, now, session_id),
            )
            self._event(c, "operator_ack", session_id, operator=operator)
            return self._session(c, session_id)

    # ------------------------------------------------------------------ planning
    def plan_trials(self, session_id: str, eval_config: EvalConfig) -> list[TrialRecord]:
        sched = build_schedule(eval_config)
        now = utcnow()
        with self.db.tx() as c:
            s = self._session(c, session_id)
            if s.state != SessionState.PLANNED:
                raise InvalidTransitionError(
                    f"trials can only be planned for a planned session, not {s.state.value}"
                )
            if s.provenance != eval_config.provenance or s.backend != eval_config.backend:
                raise ValueError(
                    f"eval_config ({eval_config.provenance.value}/{eval_config.backend}) does not match "
                    f"session ({s.provenance.value}/{s.backend})"
                )
            if c.execute("SELECT 1 FROM trials WHERE session_id=? LIMIT 1", (session_id,)).fetchone():
                raise DuplicateIdError(f"session {session_id!r} already has planned trials")
            out: list[TrialRecord] = []
            for p in sched:
                t = TrialRecord(
                    trial_id=new_id(),
                    session_id=session_id,
                    schedule_position=p.schedule_position,
                    controller_id=p.controller.controller_id,
                    controller_type=p.controller.type,
                    controller_version=p.controller.version,
                    controller_config_hash=p.controller.config_hash,
                    model_artifact_sha256=p.controller.artifact_sha256,
                    condition_name=p.condition.name,
                    condition_kind=p.condition.kind,
                    trial_index=p.trial_index,
                    seed=p.seed,
                    provenance=s.provenance,
                    backend=s.backend,
                    rubric_version=eval_config.task.rubric_version,
                    planned_at=now,
                )
                self._insert_trial(c, t)
                out.append(t)
            c.execute(
                "UPDATE sessions SET eval_config_hash=?, eval_config_json=?, updated_at=? WHERE session_id=?",
                (eval_config.config_hash, eval_config.model_dump_json(), now.isoformat(), session_id),
            )
            self._event(c, "trials_planned", session_id, count=len(out))
        return out

    @staticmethod
    def _insert_trial(c: sqlite3.Connection, t: TrialRecord) -> None:
        try:
            c.execute(
                "INSERT INTO trials(trial_id,session_id,schedule_position,controller_id,controller_type,"
                "controller_version,controller_config_hash,model_artifact_sha256,condition_name,condition_kind,"
                "trial_index,seed,provenance,backend,state,task_outcome,score_source,rubric_version,"
                "termination_reason,recording_quality,intervention,planned_at,started_at,ended_at,duration_s,"
                "reset_duration_s,artifacts_json,evidence_json,qa_flags_json,notes) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,'[]','{}','[]',?)",
                (
                    t.trial_id,
                    t.session_id,
                    t.schedule_position,
                    t.controller_id,
                    t.controller_type.value,
                    t.controller_version,
                    t.controller_config_hash,
                    t.model_artifact_sha256,
                    t.condition_name,
                    t.condition_kind,
                    t.trial_index,
                    t.seed,
                    t.provenance.value,
                    t.backend,
                    t.state.value,
                    t.task_outcome.value,
                    t.score_source.value,
                    t.rubric_version,
                    t.termination_reason.value,
                    t.recording_quality.value,
                    t.intervention.value,
                    t.planned_at.isoformat(),
                    t.notes,
                ),
            )
        except sqlite3.IntegrityError as e:
            raise DuplicateIdError(
                f"trial {t.trial_id!r} (or schedule_position {t.schedule_position} in session "
                f"{t.session_id!r}) already exists"
            ) from e

    # ------------------------------------------------------------------ trials: reads
    def get_trial(self, trial_id: str) -> TrialRecord:
        with self.db.read() as c:
            return self._trial(c, trial_id)

    def list_trials(
        self,
        session_id: str,
        state: TrialState | None = None,
        *,
        controller_id: str | None = None,
        condition_name: str | None = None,
    ) -> list[TrialRecord]:
        sql = "SELECT * FROM trials WHERE session_id=?"
        args: list[Any] = [session_id]
        if state is not None:
            sql += " AND state=?"
            args.append(state.value)
        if controller_id is not None:
            sql += " AND controller_id=?"
            args.append(controller_id)
        if condition_name is not None:
            sql += " AND condition_name=?"
            args.append(condition_name)
        sql += " ORDER BY schedule_position"
        with self.db.read() as c:
            self._session(c, session_id)
            rows = c.execute(sql, args).fetchall()
        return [row_to_trial(r) for r in rows]

    # ------------------------------------------------------------------ trials: lifecycle
    @staticmethod
    def _merge_artifacts(existing: list[ArtifactRef], new: Iterable[ArtifactRef]) -> list[ArtifactRef]:
        """Upsert by relpath (status/hash legitimately change: present -> uploaded -> verified)."""
        new_list = list(new)
        seen: set[str] = set()
        for a in new_list:
            safe_relpath(a.relpath)
            if a.relpath in seen:
                raise DuplicateIdError(f"artifact relpath {a.relpath!r} listed twice")
            seen.add(a.relpath)
        by_path = {a.relpath: a for a in existing}
        for a in new_list:
            by_path[a.relpath] = a
        return list(by_path.values())

    def transition_trial(self, trial_id: str, new_state: TrialState, **fields: Any) -> TrialRecord:
        """Validated lifecycle transition. Allowed extra fields: termination_reason, duration_s,
        reset_duration_s, started_at, ended_at, evidence (merged), intervention, notes. Scores can only be
        set through record_trial_result / score_trial / edit_score."""
        unknown = set(fields) - _TRIAL_FIELDS
        if unknown:
            raise TypeError(f"unknown trial field(s): {sorted(unknown)}; allowed: {sorted(_TRIAL_FIELDS)}")
        with self.db.tx() as c:
            t = self._trial(c, trial_id)
            return self._apply_transition(c, t, new_state, fields)

    def _apply_transition(
        self,
        c: sqlite3.Connection,
        t: TrialRecord,
        new_state: TrialState,
        fields: dict[str, Any],
        extra_cols: dict[str, Any] | None = None,
        artifacts: list[ArtifactRef] | None = None,
    ) -> TrialRecord:
        validate_trial_transition(t.state, new_state)
        now = utcnow()
        terminal = new_state in (TrialState.COMPLETED, TrialState.FAILED, TrialState.ABORTED)
        reason = fields.get("termination_reason", t.termination_reason)
        if terminal:
            _check_termination_matches_state(new_state, reason)
        cols: dict[str, Any] = {"state": new_state.value}
        if "termination_reason" in fields:
            cols["termination_reason"] = reason.value
        for k in ("duration_s", "reset_duration_s", "notes"):
            if k in fields and fields[k] is not None:
                cols[k] = fields[k]
        if "intervention" in fields and fields["intervention"] is not None:
            cols["intervention"] = Intervention(fields["intervention"]).value
        if new_state == TrialState.RUNNING and t.started_at is None:
            cols["started_at"] = (fields.get("started_at") or now).isoformat()
        elif fields.get("started_at") is not None:
            cols["started_at"] = fields["started_at"].isoformat()
        if terminal:
            cols["ended_at"] = (fields.get("ended_at") or now).isoformat()
        elif fields.get("ended_at") is not None:
            cols["ended_at"] = fields["ended_at"].isoformat()
        if fields.get("evidence"):
            cols["evidence_json"] = dumps({**t.evidence, **fields["evidence"]})
        if artifacts:
            cols["artifacts_json"] = dumps(
                [a.model_dump(mode="json") for a in self._merge_artifacts(t.artifacts, artifacts)]
            )
        if extra_cols:
            cols.update(extra_cols)
        self._update_trial(c, t.trial_id, cols)
        self._touch(c, t.session_id)
        self._event(
            c,
            "trial_transition",
            t.session_id,
            t.trial_id,
            old=t.state.value,
            new=new_state.value,
            termination_reason=reason.value,
        )
        return self._trial(c, t.trial_id)

    def record_trial_result(
        self,
        trial_id: str,
        *,
        termination_reason: TerminationReason,
        duration_s: float | None,
        task_outcome: TaskOutcome | None = None,
        score_source: ScoreSource | None = None,
        intervention: Intervention | None = None,
        evidence: dict[str, Any] | None = None,
        artifacts: list[ArtifactRef] | None = None,
        recording_quality: RecordingQuality | None = None,
        reset_duration_s: float | None = None,
    ) -> TrialRecord:
        """Finish a RUNNING trial: the terminal state follows from `termination_reason`. A task outcome may
        only accompany a COMPLETED trial (infra/abort trials stay UNSCORED) and needs a score_source."""
        new_state = state_for_termination(termination_reason)
        scored = task_outcome is not None and task_outcome != TaskOutcome.UNSCORED
        if scored:
            if new_state != TrialState.COMPLETED:
                raise ValueError(
                    f"a {new_state.value} trial ({termination_reason.value}) cannot carry a task outcome; "
                    "it stays unscored"
                )
            if score_source in (None, ScoreSource.NONE):
                raise ValueError("a task outcome requires a score_source")
        extra: dict[str, Any] = {}
        if scored:
            assert task_outcome is not None and score_source is not None
            extra["task_outcome"] = task_outcome.value
            extra["score_source"] = score_source.value
        if recording_quality is not None:
            extra["recording_quality"] = RecordingQuality(recording_quality).value
        fields: dict[str, Any] = {
            "termination_reason": termination_reason,
            "duration_s": duration_s,
            "reset_duration_s": reset_duration_s,
            "intervention": intervention,
            "evidence": evidence,
        }
        with self.db.tx() as c:
            t = self._trial(c, trial_id)
            if t.state != TrialState.RUNNING:
                raise InvalidTransitionError(
                    f"results can only be recorded for a running trial; trial is {t.state.value}"
                )
            if scored:
                assert score_source is not None
                check_score_source(t.provenance, score_source)
            return self._apply_transition(c, t, new_state, fields, extra, artifacts)

    def recover_trial(
        self, trial_id: str, *, evidence: dict[str, Any], artifacts: list[ArtifactRef]
    ) -> TrialRecord:
        """RUNNING -> ABORTED/interrupted_runner, preserving prior evidence and registering on-disk files.
        The outcome stays unscored; duration is left unset because it was never measured."""
        with self.db.tx() as c:
            t = self._trial(c, trial_id)
            if t.state != TrialState.RUNNING:
                raise InvalidTransitionError(
                    f"only running trials can be recovered; trial is {t.state.value}"
                )
            return self._apply_transition(
                c,
                t,
                TrialState.ABORTED,
                {"termination_reason": TerminationReason.INTERRUPTED_RUNNER, "evidence": evidence},
                artifacts=artifacts,
            )

    def register_artifacts(
        self,
        trial_id: str,
        artifacts: list[ArtifactRef],
        *,
        actor: str | None = None,
        reason: str | None = None,
    ) -> TrialRecord:
        """Upsert artifacts by relpath. Any change to an existing artifact's hash/size/status is
        written to the events table with the previous values. On a terminal trial, replacing a recorded
        sha256 with a different one under a good status (present/uploaded/verified) is refused unless an
        actor and reason are given;
        recording a mismatch/failure (e.g. a transfer report) is always allowed and audited."""
        with self.db.tx() as c:
            t = self._trial(c, trial_id)
            previous = {a.relpath: a for a in t.artifacts}
            terminal = t.state in (TrialState.COMPLETED, TrialState.FAILED, TrialState.ABORTED)
            good = {ArtifactStatus.PRESENT, ArtifactStatus.UPLOADED, ArtifactStatus.VERIFIED}
            changes: list[dict[str, Any]] = []
            for a in artifacts:
                old = previous.get(a.relpath)
                if old is None or (old.sha256, old.size_bytes, old.status) == (
                    a.sha256,
                    a.size_bytes,
                    a.status,
                ):
                    continue
                hash_replaced = old.sha256 is not None and a.sha256 != old.sha256
                if (
                    terminal
                    and hash_replaced
                    and a.status in good
                    and not (actor and reason and reason.strip())
                ):
                    raise ValueError(
                        f"artifact {a.relpath!r} of terminal trial {trial_id} already has sha256 "
                        f"{old.sha256}; replacing it needs actor and reason (evidence must not change silently)"  # noqa: E501
                    )
                changes.append(
                    {
                        "relpath": a.relpath,
                        "previous_sha256": old.sha256,
                        "previous_size_bytes": old.size_bytes,
                        "previous_status": old.status.value,
                        "new_sha256": a.sha256,
                        "new_size_bytes": a.size_bytes,
                        "new_status": a.status.value,
                    }
                )
            merged = self._merge_artifacts(t.artifacts, artifacts)
            self._update_trial(
                c, trial_id, {"artifacts_json": dumps([a.model_dump(mode="json") for a in merged])}
            )
            self._event(c, "artifacts_registered", t.session_id, trial_id, count=len(artifacts))
            if changes:
                self._event(
                    c,
                    "artifact_changed",
                    t.session_id,
                    trial_id,
                    changes=changes,
                    actor=actor,
                    reason=reason,
                    trial_state=t.state.value,
                )
            return self._trial(c, trial_id)

    def set_recording_quality(
        self,
        trial_id: str,
        quality: RecordingQuality,
        qa_flags: Iterable[str] = (),
        *,
        actor: str | None = None,
        reason: str | None = None,
    ) -> TrialRecord:
        """Set QA quality. The event records the previous quality, actor and reason. Moving a trial away from
        `fail` (to pass/flagged/unchecked) requires an actor and a non-empty reason."""
        quality = RecordingQuality(quality)
        flags = list(dict.fromkeys(str(f) for f in qa_flags))
        with self.db.tx() as c:
            t = self._trial(c, trial_id)
            if (
                t.recording_quality == RecordingQuality.FAIL
                and quality != RecordingQuality.FAIL
                and not (actor and actor.strip() and reason and reason.strip())
            ):
                raise ValueError(
                    f"trial {trial_id} has recording_quality=fail; changing it to {quality.value} requires "
                    "actor and a non-empty reason"
                )
            self._update_trial(
                c,
                trial_id,
                {"recording_quality": quality.value, "qa_flags_json": dumps(flags)},
            )
            self._event(
                c,
                "recording_quality",
                t.session_id,
                trial_id,
                quality=quality.value,
                previous_quality=t.recording_quality.value,
                previous_flags=t.qa_flags,
                flags=flags,
                actor=actor,
                reason=reason,
            )
            return self._trial(c, trial_id)

    def record_event(
        self, kind: str, session_id: str | None = None, trial_id: str | None = None, **detail: Any
    ) -> None:
        """Append a free-form audit event (used by the Runner for non-fatal hook failures etc.)."""
        with self.db.tx() as c:
            self._event(c, kind, session_id, trial_id, **detail)

    def list_events(self, session_id: str) -> list[dict[str, Any]]:
        with self.db.read() as c:
            rows = c.execute(
                "SELECT * FROM events WHERE session_id=? ORDER BY event_id", (session_id,)
            ).fetchall()
        return [
            {
                "at": r["at"],
                "trial_id": r["trial_id"],
                "kind": r["kind"],
                "detail": json.loads(r["detail_json"]),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------ scoring
    def score_trial(
        self,
        trial_id: str,
        outcome: TaskOutcome,
        *,
        source: ScoreSource,
        scorer: str,
        intervention: Intervention | None = None,
    ) -> TrialRecord:
        """First score only. Raises ScoreProtectionError if the trial is already scored (use edit_score)."""
        outcome = TaskOutcome(outcome)
        if outcome == TaskOutcome.UNSCORED:
            raise ValueError("score_trial needs success or failure, not unscored")
        if source == ScoreSource.NONE:
            raise ValueError("a score requires a real score_source")
        if not scorer.strip():
            raise ValueError("scorer must be non-empty")
        with self.db.tx() as c:
            t = self._trial(c, trial_id)
            check_score_source(t.provenance, source)
            if t.task_outcome != TaskOutcome.UNSCORED:
                raise ScoreProtectionError(
                    f"trial {trial_id} is already scored ({t.task_outcome.value}, source "
                    f"{t.score_source.value}); use edit_score with a reason to change it"
                )
            if t.state != TrialState.COMPLETED:
                raise InvalidTransitionError(
                    f"only completed trials can be scored; trial is {t.state.value} "
                    f"({t.termination_reason.value}) and stays unscored"
                )
            cols: dict[str, Any] = {"task_outcome": outcome.value, "score_source": source.value}
            if intervention is not None:
                cols["intervention"] = Intervention(intervention).value
            self._update_trial(c, trial_id, cols)
            self._event(c, "trial_scored", t.session_id, trial_id, outcome=outcome.value, scorer=scorer)
            return self._trial(c, trial_id)

    def edit_score(
        self,
        trial_id: str,
        outcome: TaskOutcome,
        *,
        intervention: Intervention | None = None,
        source: ScoreSource,
        editor: str,
        reason: str,
    ) -> ScoreEdit:
        """Audited change of outcome/intervention/source. Logs before and after values and the reason."""
        if not reason or not reason.strip():
            raise ValueError("edit_score requires a non-empty reason")
        if not editor or not editor.strip():
            raise ValueError("edit_score requires an editor")
        outcome = TaskOutcome(outcome)
        if outcome != TaskOutcome.UNSCORED and source == ScoreSource.NONE:
            raise ValueError("a scored outcome requires a real score_source")
        with self.db.tx() as c:
            t = self._trial(c, trial_id)
            if t.state != TrialState.COMPLETED:
                raise InvalidTransitionError(
                    f"only completed trials can be scored; trial is {t.state.value} and stays unscored"
                )
            if outcome != TaskOutcome.UNSCORED:
                check_score_source(t.provenance, source)
            new_intervention = Intervention(intervention) if intervention is not None else t.intervention
            edit = ScoreEdit(
                edit_id=new_id(),
                trial_id=trial_id,
                at=utcnow(),
                editor=editor,
                reason=reason,
                before_outcome=t.task_outcome,
                after_outcome=outcome,
                before_intervention=t.intervention,
                after_intervention=new_intervention,
                before_source=t.score_source,
                after_source=source,
            )
            self._update_trial(
                c,
                trial_id,
                {
                    "task_outcome": outcome.value,
                    "score_source": source.value,
                    "intervention": new_intervention.value,
                },
            )
            c.execute(
                "INSERT INTO score_edits(edit_id,trial_id,at,editor,reason,before_outcome,after_outcome,"
                "before_intervention,after_intervention,before_source,after_source) VALUES (?,?,?,?,?,?,?,?,?,?,?)",  # noqa: E501
                (
                    edit.edit_id,
                    trial_id,
                    edit.at.isoformat(),
                    editor,
                    reason,
                    edit.before_outcome.value,
                    edit.after_outcome.value,
                    edit.before_intervention.value,
                    edit.after_intervention.value,
                    edit.before_source.value,
                    edit.after_source.value,
                ),
            )
            self._event(c, "score_edited", t.session_id, trial_id, editor=editor)
            return edit

    def list_score_edits(self, trial_id: str) -> list[ScoreEdit]:
        with self.db.read() as c:
            self._trial(c, trial_id)
            rows = c.execute(
                "SELECT * FROM score_edits WHERE trial_id=? ORDER BY at, rowid", (trial_id,)
            ).fetchall()
        return [row_to_edit(r) for r in rows]

    # ------------------------------------------------------------------ stop requests
    def request_stop(self, session_id: str) -> bool:
        """Persist a software stop request (idempotent). Returns True the first time. NOT an e-stop."""
        with self.db.tx() as c:
            self._session(c, session_id)
            cur = c.execute(
                "INSERT OR IGNORE INTO stop_requests(session_id, requested_at) VALUES (?,?)",
                (session_id, utcnow().isoformat()),
            )
            first = cur.rowcount == 1
            if first:
                self._event(c, "stop_requested", session_id)
            return first

    def is_stop_requested(self, session_id: str) -> bool:
        with self.db.read() as c:
            return (
                c.execute("SELECT 1 FROM stop_requests WHERE session_id=?", (session_id,)).fetchone()
                is not None
            )

    # ------------------------------------------------------------------ device locks
    def acquire_device(self, device_id: str, session_id: str) -> None:
        """Take the exclusive lock for a physical device. Re-acquiring by the same session is a no-op."""
        with self.db.tx() as c:
            self._session(c, session_id)
            row = c.execute("SELECT session_id FROM device_locks WHERE device_id=?", (device_id,)).fetchone()
            if row is not None:
                if row["session_id"] == session_id:
                    return
                raise DeviceBusyError(
                    f"device {device_id!r} is locked by session {row['session_id']}; stop that runner, then run "  # noqa: E501
                    "`robotevalops session recover <id>` if it crashed"
                )
            c.execute(
                "INSERT INTO device_locks(device_id, session_id, acquired_at) VALUES (?,?,?)",
                (device_id, session_id, utcnow().isoformat()),
            )
            self._event(c, "device_acquired", session_id, device_id=device_id)

    def release_device(self, device_id: str, session_id: str) -> bool:
        """Release the lock if `session_id` owns it. Returns whether a lock was released."""
        with self.db.tx() as c:
            cur = c.execute(
                "DELETE FROM device_locks WHERE device_id=? AND session_id=?", (device_id, session_id)
            )
            if cur.rowcount:
                self._event(c, "device_released", session_id, device_id=device_id)
            return bool(cur.rowcount)

    def release_locks_for_session(self, session_id: str) -> list[str]:
        with self.db.tx() as c:
            ids = [
                r["device_id"]
                for r in c.execute(
                    "SELECT device_id FROM device_locks WHERE session_id=?", (session_id,)
                ).fetchall()
            ]
            c.execute("DELETE FROM device_locks WHERE session_id=?", (session_id,))
            for d in ids:
                self._event(c, "device_released", session_id, device_id=d, reason="recovery")
            return ids

    def device_lock_holder(self, device_id: str) -> str | None:
        with self.db.read() as c:
            r = c.execute("SELECT session_id FROM device_locks WHERE device_id=?", (device_id,)).fetchone()
        return r["session_id"] if r else None

    # ------------------------------------------------------------------ recovery (see core/recovery.py)
    def find_interrupted(self) -> list[SessionRecord]:
        from robotevalops.core.recovery import find_interrupted

        return find_interrupted(self)

    def recover_interrupted(self, session_id: str) -> list[TrialRecord]:
        from robotevalops.core.recovery import recover_interrupted

        return recover_interrupted(self, session_id)

    # ------------------------------------------------------------------ manifest
    def export_manifest(self, session_id: str) -> RunManifest:
        """Manifest covering EVERY planned trial (attempted or not), with the session calibration_ref."""
        s = self.get_session(session_id)
        trials = self.list_trials(session_id)
        return RunManifest(
            session_id=s.session_id,
            provenance=s.provenance,
            backend=s.backend,
            task_id=s.task.task_id,
            rubric_version=s.task.rubric_version,
            git_commit=s.git_commit,
            software=s.software,
            eval_config_hash=s.eval_config_hash,
            created_at=s.created_at,
            trials=[
                TrialManifestEntry(
                    trial_id=t.trial_id,
                    state=t.state,
                    task_outcome=t.task_outcome,
                    termination_reason=t.termination_reason,
                    recording_quality=t.recording_quality,
                    intervention=t.intervention,
                    condition_name=t.condition_name,
                    controller_id=t.controller_id,
                    controller_type=t.controller_type,
                    controller_config_hash=t.controller_config_hash,
                    model_artifact_sha256=t.model_artifact_sha256,
                    seed=t.seed,
                    duration_s=t.duration_s,
                    provenance=t.provenance,
                    artifacts=t.artifacts,
                    calibration_ref=s.calibration_ref,
                )
                for t in trials
            ],
        )
