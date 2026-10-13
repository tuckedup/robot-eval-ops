"""Metrics over TrialRecords with EXACTLY the denominators of docs/contracts.md section 5.

planned    = every trial given (rows never vanish)
attempted  = started_at set (reached RUNNING)
evaluable  = COMPLETED and scored (success|failure) and recording_quality != fail
Autonomous success is `schemas.is_autonomous_success` (assisted/unknown intervention never counts).
Nothing is imputed: durations come only from recorded values; empty denominators yield None.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import BaseModel, Field

from robotevalops.metrics.stats import describe, rate, wilson_interval
from robotevalops.schemas import (
    INFRA_REASONS,
    ArtifactRef,
    ArtifactRole,
    ArtifactStatus,
    Intervention,
    Provenance,
    RecordingQuality,
    TaskOutcome,
    TrialRecord,
    TrialState,
    is_autonomous_success,
)

MOCK_BANNER = "MOCK FIXTURE — not evidence of robotics performance"
SMALL_N = 20  # below this many denominator trials, intervals are wide and claims are weak
EXPECTED_ROLES = (ArtifactRole.VIDEO, ArtifactRole.TRACE)
_PRESENT = {ArtifactStatus.PRESENT, ArtifactStatus.UPLOADED, ArtifactStatus.VERIFIED}
_TRANSFERRED = {ArtifactStatus.UPLOADED, ArtifactStatus.VERIFIED, ArtifactStatus.MISMATCH}


class Rate(BaseModel):
    """A proportion with explicit numerator/denominator. rate/ci are None when n == 0."""

    k: int
    n: int
    rate: float | None
    ci_low: float | None = None
    ci_high: float | None = None
    ci_method: str = "wilson_95"

    @classmethod
    def of(cls, k: int, n: int) -> Rate:
        ci = wilson_interval(k, n)
        return cls(k=k, n=n, rate=rate(k, n), ci_low=ci[0] if ci else None, ci_high=ci[1] if ci else None)

    def fmt(self) -> str:
        if self.rate is None:
            return "n/a (n=0)"
        ci = f" [{self.ci_low:.3f}, {self.ci_high:.3f}]" if self.ci_low is not None else ""
        return f"{self.rate:.3f} ({self.k}/{self.n}){ci}"


class DurationStats(BaseModel):
    n: int
    mean: float | None
    median: float | None
    min: float | None
    max: float | None
    p95: float | None
    note: str = ""

    @classmethod
    def of(cls, values: Sequence[float], what: str) -> DurationStats:
        d = describe(values)
        note = f"{what}: n={d['n']} recorded value(s) only; nothing imputed."
        if d["p95"] is None and d["n"]:
            note += " 95th percentile not reported (needs n >= 20)."
        return cls(note=note, **d)


class ArtifactCompleteness(BaseModel):
    """present+hash-recorded / expected. Expected = every registered artifact of an attempted trial plus
    one video and one trace per attempted trial (a missing registration counts as missing)."""

    expected: int
    present_with_hash: int
    completeness: Rate
    missing: int
    quarantined: int
    checksum_verified: int
    checksum_mismatch: int
    checksum_unverified: int  # hash recorded, not yet re-verified after transfer
    checksum_agreement: Rate  # verified / transferred (uploaded+verified+mismatch)


class GroupMetrics(BaseModel):
    key: dict[str, str]
    provenances: list[str]
    controller_types: list[str]
    session_ids: list[str]
    planned: int
    attempted: int
    completed: int
    failed: int
    aborted: int
    not_attempted: int
    unscored: int  # attempted with task_outcome == unscored
    evaluable: int
    autonomous_successes: int
    assisted_successes: int
    unknown_intervention_successes: int
    success_per_attempt: Rate
    success_per_evaluable: Rate
    intervention_rate: Rate
    infra_abort_rate: Rate
    infra_reasons_not_attempted: int
    recording_pass_rate: Rate
    quality_excluded: int  # completed+scored but recording_quality == fail
    duration: DurationStats
    reset_duration: DurationStats
    artifacts: ArtifactCompleteness
    warnings: list[str] = Field(default_factory=list)


class MetricsReport(BaseModel):
    provenances: list[str]
    controller_types: list[str]
    session_ids: list[str]
    banner: str | None
    overall: GroupMetrics
    by_condition: list[GroupMetrics]
    by_controller: list[GroupMetrics]
    by_controller_condition: list[GroupMetrics]
    warnings: list[str]
    denominator_definitions: dict[str, str]


DEFINITIONS = {
    "planned": "all trials given (never-attempted trials stay here)",
    "attempted": "started_at set (reached RUNNING)",
    "completed/failed/aborted": "lifecycle state counts",
    "unscored": "attempted trials with task_outcome=unscored",
    "evaluable": "COMPLETED, scored success|failure, recording_quality != fail",
    "success_per_attempt": "autonomous successes / attempted",
    "success_per_evaluable": "autonomous successes / evaluable",
    "intervention_rate": "intervention == assisted / attempted",
    "infra_abort_rate": "attempted trials terminated by an infra reason / attempted",
    "recording_pass_rate": "recording_quality == pass / attempted",
    "artifact_completeness": "present+hash-recorded / expected (expected includes video+trace per attempt)",
    "checksum_agreement": "verified / transferred (uploaded+verified+mismatch)",
}


def artifact_completeness(trials: Iterable[TrialRecord]) -> ArtifactCompleteness:
    expected = present = missing = quarantined = verified = mismatch = unverified = transferred = 0
    for t in trials:
        if not t.is_attempted:
            continue
        by_rel: dict[str, ArtifactRef] = {a.relpath: a for a in t.artifacts}
        refs = list(by_rel.values())
        have_roles = {a.role for a in refs}
        unregistered = sum(1 for r in EXPECTED_ROLES if r not in have_roles)
        expected += len(refs) + unregistered
        missing += unregistered
        for a in refs:
            if a.status in _PRESENT and a.sha256:
                present += 1
            elif a.status == ArtifactStatus.QUARANTINED:
                quarantined += 1
            elif a.status in (ArtifactStatus.MISSING, ArtifactStatus.FAILED, ArtifactStatus.PENDING):
                missing += 1
            if a.status == ArtifactStatus.VERIFIED:
                verified += 1
            elif a.status == ArtifactStatus.MISMATCH:
                mismatch += 1
            elif a.status in _PRESENT and a.sha256:
                unverified += 1
            if a.status in _TRANSFERRED:
                transferred += 1
    return ArtifactCompleteness(
        expected=expected,
        present_with_hash=present,
        completeness=Rate.of(present, expected),
        missing=missing,
        quarantined=quarantined,
        checksum_verified=verified,
        checksum_mismatch=mismatch,
        checksum_unverified=unverified,
        checksum_agreement=Rate.of(verified, transferred),
    )


def _group_warnings(g: GroupMetrics) -> list[str]:
    w: list[str] = []
    label = ", ".join(f"{k}={v}" for k, v in g.key.items()) or "overall"
    if g.planned == 0:
        w.append(f"[{label}] no trials: every rate is undefined (n=0).")
        return w
    if g.not_attempted:
        w.append(
            f"[{label}] {g.not_attempted} of {g.planned} planned trial(s) were never attempted; "
            "the run is incomplete and rates use the stated denominators."
        )
    if g.unscored:
        w.append(f"[{label}] {g.unscored} attempted trial(s) are unscored (infra/abort or awaiting scoring).")
    if g.attempted and g.evaluable < SMALL_N:
        w.append(
            f"[{label}] small n: {g.evaluable} evaluable trial(s) (< {SMALL_N}); intervals are wide "
            "and differences are not reliable."
        )
    if g.attempted and g.duration.n < g.attempted:
        w.append(
            f"[{label}] duration recorded for {g.duration.n} of {g.attempted} attempted trials; "
            "durations exclude the others."
        )
    if g.quality_excluded:
        w.append(
            f"[{label}] {g.quality_excluded} scored trial(s) excluded from 'evaluable' by recording "
            "quality = fail (shown, not hidden)."
        )
    if g.assisted_successes or g.unknown_intervention_successes:
        w.append(
            f"[{label}] {g.assisted_successes} assisted and {g.unknown_intervention_successes} "
            "unknown-intervention success(es) are NOT counted as autonomous."
        )
    if g.artifacts.missing:
        w.append(f"[{label}] {g.artifacts.missing} expected artifact(s) missing/pending/failed.")
    if g.artifacts.checksum_mismatch:
        w.append(f"[{label}] {g.artifacts.checksum_mismatch} artifact checksum mismatch(es).")
    if len(g.provenances) > 1:
        w.append(f"[{label}] mixes provenance {g.provenances}; do not pool these results.")
    return w


def compute_group(trials: Sequence[TrialRecord], key: dict[str, str] | None = None) -> GroupMetrics:
    ts = list(trials)
    attempted_t = [t for t in ts if t.is_attempted]
    scored = [
        t
        for t in ts
        if t.state == TrialState.COMPLETED and t.task_outcome in (TaskOutcome.SUCCESS, TaskOutcome.FAILURE)
    ]
    evaluable = [t for t in scored if t.recording_quality != RecordingQuality.FAIL]
    auto = sum(is_autonomous_success(t) for t in ts)
    n_att = len(attempted_t)
    succ = [t for t in ts if t.state == TrialState.COMPLETED and t.task_outcome == TaskOutcome.SUCCESS]
    g = GroupMetrics(
        key=key or {},
        provenances=sorted({t.provenance.value for t in ts}),
        controller_types=sorted({t.controller_type.value for t in ts}),
        session_ids=sorted({t.session_id for t in ts}),
        planned=len(ts),
        attempted=n_att,
        completed=sum(t.state == TrialState.COMPLETED for t in ts),
        failed=sum(t.state == TrialState.FAILED for t in ts),
        aborted=sum(t.state == TrialState.ABORTED for t in ts),
        not_attempted=len(ts) - n_att,
        unscored=sum(t.task_outcome == TaskOutcome.UNSCORED for t in attempted_t),
        evaluable=len(evaluable),
        autonomous_successes=auto,
        assisted_successes=sum(t.intervention == Intervention.ASSISTED for t in succ),
        unknown_intervention_successes=sum(t.intervention == Intervention.UNKNOWN for t in succ),
        success_per_attempt=Rate.of(auto, n_att),
        success_per_evaluable=Rate.of(auto, len(evaluable)),
        intervention_rate=Rate.of(sum(t.intervention == Intervention.ASSISTED for t in attempted_t), n_att),
        infra_abort_rate=Rate.of(sum(t.termination_reason in INFRA_REASONS for t in attempted_t), n_att),
        infra_reasons_not_attempted=sum(
            t.termination_reason in INFRA_REASONS for t in ts if not t.is_attempted
        ),
        recording_pass_rate=Rate.of(
            sum(t.recording_quality == RecordingQuality.PASS for t in attempted_t), n_att
        ),
        quality_excluded=len(scored) - len(evaluable),
        duration=DurationStats.of([t.duration_s for t in ts if t.duration_s is not None], "trial duration"),
        reset_duration=DurationStats.of(
            [t.reset_duration_s for t in ts if t.reset_duration_s is not None], "reset duration"
        ),
        artifacts=artifact_completeness(ts),
    )
    g.warnings = _group_warnings(g)
    return g


def _controller_key(t: TrialRecord) -> tuple[str, ...]:
    return (t.controller_id, t.controller_version, t.controller_type.value, t.provenance.value)


def compute_metrics(trials: Sequence[TrialRecord]) -> MetricsReport:
    ts = list(trials)
    overall = compute_group(ts)

    def _group(keyfn: Any, keynames: tuple[str, ...]) -> list[GroupMetrics]:
        buckets: dict[tuple[str, ...], list[TrialRecord]] = {}
        for t in ts:
            buckets.setdefault(keyfn(t), []).append(t)
        return [compute_group(v, dict(zip(keynames, k, strict=True))) for k, v in sorted(buckets.items())]

    ckeys = ("controller_id", "controller_version", "controller_type", "provenance")
    by_condition = _group(lambda t: (t.condition_name, t.provenance.value), ("condition", "provenance"))
    by_controller = _group(_controller_key, ckeys)
    by_cc = _group(lambda t: (*_controller_key(t), t.condition_name), (*ckeys, "condition"))
    banner = MOCK_BANNER if any(t.provenance == Provenance.MOCK for t in ts) else None
    return MetricsReport(
        provenances=overall.provenances,
        controller_types=overall.controller_types,
        session_ids=overall.session_ids,
        banner=banner,
        overall=overall,
        by_condition=by_condition,
        by_controller=by_controller,
        by_controller_condition=by_cc,
        warnings=list(overall.warnings),
        denominator_definitions=dict(DEFINITIONS),
    )
