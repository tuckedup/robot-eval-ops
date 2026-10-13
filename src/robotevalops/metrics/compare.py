"""Paired controller comparison. Pairing key: (condition_name, trial_index); seeds must match (the scheduler
derives the seed from base_seed/condition/index only). Unpaired or ineligible partners are LISTED, never
silently dropped. Success = autonomous success. A pair is analysable only if both trials are evaluable."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field

from robotevalops.metrics.compute import Rate
from robotevalops.metrics.stats import exact_mcnemar_p
from robotevalops.schemas import (
    RecordingQuality,
    TaskOutcome,
    TrialRecord,
    TrialState,
    is_autonomous_success,
)

SIGNIFICANCE_CAVEAT = (
    "The exact McNemar p-value uses only discordant pairs. With the small n typical here it does not "
    "support significance claims: it assumes independent pairs, a fixed paired design, and a pre-specified "
    "test, and ignores multiple comparisons across conditions. Treat differences as descriptive."
)


class PairIssue(BaseModel):
    condition: str
    trial_index: int
    reason: str  # missing_partner | not_evaluable_a | not_evaluable_b | seed_mismatch | duplicate
    trial_id_a: str | None = None
    trial_id_b: str | None = None


class PairedCell(BaseModel):
    condition: str
    pairs: int
    both: int
    a_only: int
    b_only: int
    neither: int
    a_success: Rate
    b_success: Rate
    p_value_exact_mcnemar: float | None


class Comparison(BaseModel):
    controller_a: str
    controller_b: str
    provenances: list[str]
    controller_types: dict[str, list[str]]
    overall: PairedCell
    by_condition: list[PairedCell]
    unpaired: list[PairIssue] = Field(default_factory=list)
    caveat: str = SIGNIFICANCE_CAVEAT
    notes: list[str] = Field(default_factory=list)


def _evaluable(t: TrialRecord) -> bool:
    return (
        t.state == TrialState.COMPLETED
        and t.task_outcome in (TaskOutcome.SUCCESS, TaskOutcome.FAILURE)
        and t.recording_quality != RecordingQuality.FAIL
    )


def _cell(name: str, pairs: list[tuple[TrialRecord, TrialRecord]]) -> PairedCell:
    both = a_only = b_only = neither = 0
    for a, b in pairs:
        sa, sb = is_autonomous_success(a), is_autonomous_success(b)
        both += int(sa and sb)
        a_only += int(sa and not sb)
        b_only += int(sb and not sa)
        neither += int(not sa and not sb)
    return PairedCell(
        condition=name,
        pairs=len(pairs),
        both=both,
        a_only=a_only,
        b_only=b_only,
        neither=neither,
        a_success=Rate.of(both + a_only, len(pairs)),
        b_success=Rate.of(both + b_only, len(pairs)),
        p_value_exact_mcnemar=exact_mcnemar_p(a_only, b_only),
    )


def compare_controllers(trials: Sequence[TrialRecord], controller_a: str, controller_b: str) -> Comparison:
    ts = list(trials)
    a_ts = [t for t in ts if t.controller_id == controller_a]
    b_ts = [t for t in ts if t.controller_id == controller_b]
    idx_a: dict[tuple[str, int], list[TrialRecord]] = {}
    idx_b: dict[tuple[str, int], list[TrialRecord]] = {}
    for t in a_ts:
        idx_a.setdefault((t.condition_name, t.trial_index), []).append(t)
    for t in b_ts:
        idx_b.setdefault((t.condition_name, t.trial_index), []).append(t)
    pairs: dict[str, list[tuple[TrialRecord, TrialRecord]]] = {}
    issues: list[PairIssue] = []
    conds = {t.condition_name for t in a_ts + b_ts}
    for key in sorted(set(idx_a) | set(idx_b)):
        cond, ti = key
        la, lb = idx_a.get(key, []), idx_b.get(key, [])
        ida = la[0].trial_id if la else None
        idb = lb[0].trial_id if lb else None
        if len(la) > 1 or len(lb) > 1:
            reason: str | None = "duplicate"
        elif not la or not lb:
            reason = "missing_partner"
        elif la[0].seed != lb[0].seed:
            reason = "seed_mismatch"
        elif not _evaluable(la[0]):
            reason = "not_evaluable_a"
        elif not _evaluable(lb[0]):
            reason = "not_evaluable_b"
        else:
            reason = None
        if reason:
            issues.append(
                PairIssue(condition=cond, trial_index=ti, reason=reason, trial_id_a=ida, trial_id_b=idb)
            )
        else:
            pairs.setdefault(cond, []).append((la[0], lb[0]))
    all_pairs = [p for c in sorted(pairs) for p in pairs[c]]
    notes = []
    if issues:
        notes.append(f"{len(issues)} trial position(s) could not be analysed as pairs; see 'unpaired'.")
    if not a_ts or not b_ts:
        notes.append("one of the controllers has no trials in the selected data.")
    return Comparison(
        controller_a=controller_a,
        controller_b=controller_b,
        provenances=sorted({t.provenance.value for t in a_ts + b_ts}),
        controller_types={
            controller_a: sorted({t.controller_type.value for t in a_ts}),
            controller_b: sorted({t.controller_type.value for t in b_ts}),
        },
        overall=_cell("ALL", all_pairs),
        by_condition=[_cell(c, pairs.get(c, [])) for c in sorted(conds)],
        unpaired=issues,
        notes=notes,
    )
