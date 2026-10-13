"""Crash recovery. After a runner dies, RUNNING trials become ABORTED/interrupted_runner with their evidence
and on-disk files preserved, the session returns to PREFLIGHT with requires_fresh_preflight=True, and any
device lock held by the session is released. Recovery never resumes motion and never marks a trial success.
Idempotent: running it again changes nothing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from robotevalops.core.files import scan_dir
from robotevalops.schemas import (
    ArtifactStatus,
    SessionRecord,
    SessionState,
    TrialRecord,
    TrialState,
)
from robotevalops.util import utcnow

if TYPE_CHECKING:
    from robotevalops.core.service import EvalService


def find_interrupted(service: EvalService) -> list[SessionRecord]:
    """Sessions that look like a runner died: state RUNNING, or any trial still RUNNING.
    (A live runner in another process is indistinguishable; recover only after stopping it.)"""
    out: list[SessionRecord] = []
    with service.db.read() as c:
        ids = [
            r["session_id"]
            for r in c.execute(
                "SELECT session_id FROM sessions WHERE state=? "
                "UNION SELECT session_id FROM trials WHERE state=? ORDER BY 1",
                (SessionState.RUNNING.value, TrialState.RUNNING.value),
            ).fetchall()
        ]
    for sid in ids:
        out.append(service.get_session(sid))
    return out


def recover_interrupted(service: EvalService, session_id: str) -> list[TrialRecord]:
    """Recover one session. Returns the trials that were moved from RUNNING to ABORTED."""
    session = service.get_session(session_id)
    running = service.list_trials(session_id, TrialState.RUNNING)
    recovered: list[TrialRecord] = []
    run_dir = service.run_dir(session_id)
    for t in running:
        tdir = service.trial_dir(session_id, t.trial_id)
        on_disk = scan_dir(run_dir, tdir)
        disk_paths = {a.relpath for a in on_disk}
        registered_missing = [
            a.model_copy(
                update={"status": ArtifactStatus.MISSING, "detail": "registered but not on disk after crash"}
            )
            for a in t.artifacts
            if a.relpath not in disk_paths
        ]
        evidence = {
            "interrupted_runner": {
                "recovered_at": utcnow().isoformat(),
                "files_on_disk": sorted(disk_paths),
                "note": "runner died while the trial was RUNNING; partial files preserved, task not judged",
            }
        }
        recovered.append(
            service.recover_trial(t.trial_id, evidence=evidence, artifacts=[*on_disk, *registered_missing])
        )
    if session.state == SessionState.RUNNING:
        service.transition_session(
            session_id, SessionState.PREFLIGHT, note="recovered after runner interruption"
        )
    if recovered or session.state == SessionState.RUNNING:
        service.flag_fresh_preflight(session_id)
    service.release_locks_for_session(session_id)
    return recovered
