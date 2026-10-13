"""Documented allowed lifecycle transitions (lead-owned, pure data + validator).

Trial:    planned -> preflight -> ready -> running -> completed | failed | aborted
Session:  same shape; recovery after a crash moves running -> preflight (never to running).
`task_outcome` is NOT a lifecycle state; it is scored separately.
"""

from __future__ import annotations

from robotevalops.errors import InvalidTransitionError
from robotevalops.schemas import SessionState as S
from robotevalops.schemas import TrialState as T

TRIAL_TRANSITIONS: dict[T, frozenset[T]] = {
    T.PLANNED: frozenset({T.PREFLIGHT, T.ABORTED}),
    T.PREFLIGHT: frozenset({T.READY, T.FAILED, T.ABORTED}),
    T.READY: frozenset({T.RUNNING, T.PREFLIGHT, T.ABORTED}),  # READY->PREFLIGHT: re-check after a pause
    T.RUNNING: frozenset({T.COMPLETED, T.FAILED, T.ABORTED}),
    T.COMPLETED: frozenset(),
    T.FAILED: frozenset(),
    T.ABORTED: frozenset(),
}

SESSION_TRANSITIONS: dict[S, frozenset[S]] = {
    S.PLANNED: frozenset({S.PREFLIGHT, S.ABORTED}),
    S.PREFLIGHT: frozenset({S.READY, S.FAILED, S.ABORTED}),
    S.READY: frozenset({S.RUNNING, S.PREFLIGHT, S.ABORTED}),
    # RUNNING -> PREFLIGHT is the crash-recovery edge only (requires fresh preflight).
    S.RUNNING: frozenset({S.COMPLETED, S.FAILED, S.ABORTED, S.READY, S.PREFLIGHT}),
    S.COMPLETED: frozenset(),
    S.FAILED: frozenset(),
    S.ABORTED: frozenset(),
}


def validate_trial_transition(old: T, new: T) -> None:
    if new not in TRIAL_TRANSITIONS[old]:
        allowed = sorted(x.value for x in TRIAL_TRANSITIONS[old]) or ["(terminal)"]
        raise InvalidTransitionError(
            f"trial transition {old.value} -> {new.value} not allowed; allowed from {old.value}: {allowed}"
        )


def validate_session_transition(old: S, new: S) -> None:
    if new not in SESSION_TRANSITIONS[old]:
        allowed = sorted(x.value for x in SESSION_TRANSITIONS[old]) or ["(terminal)"]
        raise InvalidTransitionError(
            f"session transition {old.value} -> {new.value} not allowed; allowed from {old.value}: {allowed}"
        )
