"""Failure-category table. Every trial lands in exactly one row: nothing is dropped, and
unscored/incomplete trials are visible. Counts per (controller, condition) sum to its planned count."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from pydantic import BaseModel

from robotevalops.schemas import (
    INFRA_REASONS,
    TaskOutcome,
    TrialRecord,
    TrialState,
    is_autonomous_success,
)


def failure_class(t: TrialRecord) -> str:
    """autonomous_success | non_autonomous_success | task_failure | completed_unscored | infra_failure |
    aborted_operator_or_stop | aborted_infra | not_attempted | in_progress."""
    if t.state == TrialState.COMPLETED:
        if is_autonomous_success(t):
            return "autonomous_success"
        if t.task_outcome == TaskOutcome.SUCCESS:
            return "non_autonomous_success"  # assisted/unknown intervention or recording quality fail
        if t.task_outcome == TaskOutcome.FAILURE:
            return "task_failure"
        return "completed_unscored"
    if t.state == TrialState.FAILED:
        return "infra_failure"
    if t.state == TrialState.ABORTED:
        if not t.is_attempted:
            return "not_attempted"
        return "aborted_infra" if t.termination_reason in INFRA_REASONS else "aborted_operator_or_stop"
    return "not_attempted" if not t.is_attempted else "in_progress"


class FailureRow(BaseModel):
    controller_id: str
    controller_type: str
    provenance: str
    condition: str
    failure_class: str
    state: str
    termination_reason: str
    task_outcome: str
    intervention: str
    count: int


class FailureReport(BaseModel):
    rows: list[FailureRow]
    qa_flag_counts: dict[str, int]
    total_trials: int
    class_totals: dict[str, int]
    note: str = (
        "Every trial appears in exactly one row. infra/abort trials stay unscored and are never "
        "counted as task failures; task failures are completed trials scored failure."
    )


def failure_report(trials: Sequence[TrialRecord]) -> FailureReport:
    ts = list(trials)
    counts: Counter[tuple[str, ...]] = Counter()
    flags: Counter[str] = Counter()
    classes: Counter[str] = Counter()
    for t in ts:
        cls = failure_class(t)
        classes[cls] += 1
        counts[
            (
                t.controller_id,
                t.controller_type.value,
                t.provenance.value,
                t.condition_name,
                cls,
                t.state.value,
                t.termination_reason.value,
                t.task_outcome.value,
                t.intervention.value,
            )
        ] += 1
        flags.update(t.qa_flags)
    rows = [
        FailureRow(
            controller_id=k[0],
            controller_type=k[1],
            provenance=k[2],
            condition=k[3],
            failure_class=k[4],
            state=k[5],
            termination_reason=k[6],
            task_outcome=k[7],
            intervention=k[8],
            count=v,
        )
        for k, v in sorted(counts.items())
    ]
    return FailureReport(
        rows=rows,
        qa_flag_counts=dict(sorted(flags.items())),
        total_trials=len(ts),
        class_totals=dict(sorted(classes.items())),
    )
