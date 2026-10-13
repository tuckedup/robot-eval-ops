"""SQLite persistence for sessions/trials/score edits/device locks/stop requests/events.

Every mutation runs inside a `BEGIN IMMEDIATE` transaction obtained from `Database.tx()`, so concurrent
writers (threads or processes) are serialised by SQLite and never observe partial updates. Connections are
opened per operation (cheap for SQLite) so the module is safe to share between threads.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from robotevalops.errors import SchemaMismatchError
from robotevalops.schemas import (
    ArtifactRef,
    ControllerType,
    Intervention,
    Provenance,
    RecordingQuality,
    ScoreEdit,
    ScoreSource,
    SessionRecord,
    SessionState,
    TaskOutcome,
    TaskSpec,
    TerminationReason,
    TrialRecord,
    TrialState,
)

DB_SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 30_000

_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    state TEXT NOT NULL,
    provenance TEXT NOT NULL,
    backend TEXT NOT NULL,
    task_json TEXT NOT NULL,
    purpose TEXT NOT NULL,
    operator TEXT NOT NULL,
    device_id TEXT,
    calibration_ref TEXT,
    eval_config_hash TEXT,
    eval_config_json TEXT,
    software_json TEXT NOT NULL,
    git_commit TEXT,
    requires_fresh_preflight INTEGER NOT NULL DEFAULT 0,
    operator_ack_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    schema_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trials (
    trial_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    schedule_position INTEGER NOT NULL,
    controller_id TEXT NOT NULL,
    controller_type TEXT NOT NULL,
    controller_version TEXT NOT NULL,
    controller_config_hash TEXT NOT NULL,
    model_artifact_sha256 TEXT,
    condition_name TEXT NOT NULL,
    condition_kind TEXT NOT NULL,
    trial_index INTEGER NOT NULL,
    seed INTEGER NOT NULL,
    provenance TEXT NOT NULL,
    backend TEXT NOT NULL,
    state TEXT NOT NULL,
    task_outcome TEXT NOT NULL,
    score_source TEXT NOT NULL,
    rubric_version TEXT NOT NULL,
    termination_reason TEXT NOT NULL,
    recording_quality TEXT NOT NULL,
    intervention TEXT NOT NULL,
    planned_at TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    duration_s REAL,
    reset_duration_s REAL,
    artifacts_json TEXT NOT NULL DEFAULT '[]',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    qa_flags_json TEXT NOT NULL DEFAULT '[]',
    notes TEXT NOT NULL DEFAULT '',
    UNIQUE (session_id, schedule_position)
);
CREATE INDEX IF NOT EXISTS idx_trials_session_state ON trials(session_id, state);
CREATE TABLE IF NOT EXISTS score_edits (
    edit_id TEXT PRIMARY KEY,
    trial_id TEXT NOT NULL REFERENCES trials(trial_id),
    at TEXT NOT NULL,
    editor TEXT NOT NULL,
    reason TEXT NOT NULL,
    before_outcome TEXT NOT NULL,
    after_outcome TEXT NOT NULL,
    before_intervention TEXT NOT NULL,
    after_intervention TEXT NOT NULL,
    before_source TEXT NOT NULL,
    after_source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_score_edits_trial ON score_edits(trial_id, at);
CREATE TABLE IF NOT EXISTS device_locks (
    device_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    acquired_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stop_requests (
    session_id TEXT PRIMARY KEY REFERENCES sessions(session_id),
    requested_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    session_id TEXT,
    trial_id TEXT,
    kind TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, event_id);
"""


class Database:
    """Thin SQLite wrapper. `Database(path)` creates the file and schema on first use."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ------------------------------------------------------------------ connections
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        with closing(self._connect()) as conn:
            yield conn

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Write transaction (BEGIN IMMEDIATE). Commits on success, rolls back on any exception."""
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
        with self.tx() as c:
            for stmt in _split_ddl(_DDL):
                c.execute(stmt)
            row = c.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
            current = row["v"] if row and row["v"] is not None else None
            if current is None:
                c.execute(
                    "INSERT INTO schema_version(version, applied_at) VALUES (?, ?)",
                    (DB_SCHEMA_VERSION, datetime_now_iso()),
                )
            elif current > DB_SCHEMA_VERSION:
                raise SchemaMismatchError(
                    f"database {self.path} has schema version {current}, this build supports "
                    f"{DB_SCHEMA_VERSION}; upgrade RobotEvalOps or use a different --home"
                )

    def schema_version(self) -> int:
        with self.read() as c:
            return int(c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0])


def _split_ddl(ddl: str) -> list[str]:
    return [s.strip() for s in ddl.split(";") if s.strip()]


def datetime_now_iso() -> str:
    from robotevalops.util import utcnow

    return utcnow().isoformat()


# --------------------------------------------------------------------------- row converters


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


def row_to_session(r: sqlite3.Row) -> SessionRecord:
    return SessionRecord(
        session_id=r["session_id"],
        name=r["name"],
        state=SessionState(r["state"]),
        provenance=Provenance(r["provenance"]),
        backend=r["backend"],
        task=TaskSpec.model_validate(json.loads(r["task_json"])),
        purpose=r["purpose"],
        operator=r["operator"],
        device_id=r["device_id"],
        calibration_ref=r["calibration_ref"],
        eval_config_hash=r["eval_config_hash"],
        software=json.loads(r["software_json"]),
        git_commit=r["git_commit"],
        requires_fresh_preflight=bool(r["requires_fresh_preflight"]),
        operator_ack_at=_dt(r["operator_ack_at"]),
        created_at=datetime.fromisoformat(r["created_at"]),
        updated_at=datetime.fromisoformat(r["updated_at"]),
        notes=r["notes"],
        schema_version=r["schema_version"],
    )


def row_to_trial(r: sqlite3.Row) -> TrialRecord:
    return TrialRecord(
        trial_id=r["trial_id"],
        session_id=r["session_id"],
        schedule_position=r["schedule_position"],
        controller_id=r["controller_id"],
        controller_type=ControllerType(r["controller_type"]),
        controller_version=r["controller_version"],
        controller_config_hash=r["controller_config_hash"],
        model_artifact_sha256=r["model_artifact_sha256"],
        condition_name=r["condition_name"],
        condition_kind=r["condition_kind"],
        trial_index=r["trial_index"],
        seed=r["seed"],
        provenance=Provenance(r["provenance"]),
        backend=r["backend"],
        state=TrialState(r["state"]),
        task_outcome=TaskOutcome(r["task_outcome"]),
        score_source=ScoreSource(r["score_source"]),
        rubric_version=r["rubric_version"],
        termination_reason=TerminationReason(r["termination_reason"]),
        recording_quality=RecordingQuality(r["recording_quality"]),
        intervention=Intervention(r["intervention"]),
        planned_at=datetime.fromisoformat(r["planned_at"]),
        started_at=_dt(r["started_at"]),
        ended_at=_dt(r["ended_at"]),
        duration_s=r["duration_s"],
        reset_duration_s=r["reset_duration_s"],
        artifacts=[ArtifactRef.model_validate(a) for a in json.loads(r["artifacts_json"])],
        evidence=json.loads(r["evidence_json"]),
        qa_flags=json.loads(r["qa_flags_json"]),
        notes=r["notes"],
    )


def row_to_edit(r: sqlite3.Row) -> ScoreEdit:
    return ScoreEdit(
        edit_id=r["edit_id"],
        trial_id=r["trial_id"],
        at=datetime.fromisoformat(r["at"]),
        editor=r["editor"],
        reason=r["reason"],
        before_outcome=TaskOutcome(r["before_outcome"]),
        after_outcome=TaskOutcome(r["after_outcome"]),
        before_intervention=Intervention(r["before_intervention"]),
        after_intervention=Intervention(r["after_intervention"]),
        before_source=ScoreSource(r["before_source"]),
        after_source=ScoreSource(r["after_source"]),
    )
