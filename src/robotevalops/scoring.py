"""Operator/human scoring workflow over the public EvalService API.

Sim/mock auto-scores are written by the Runner. This module supports human video scoring (hardware or
imported recordings): a required scorer name, an explicit intervention judgement, and the rubric version, plus
inter-scorer agreement (percent agreement and Cohen's kappa, computed by hand). No agreement number is ever
produced without two real scorers' labels.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from robotevalops.core.service import EvalService
from robotevalops.errors import RobotEvalOpsError
from robotevalops.schemas import (
    Intervention,
    ScoreEdit,
    ScoreSource,
    TaskOutcome,
    TrialRecord,
    TrialState,
)
from robotevalops.util import RUBRIC_VERSION

HUMAN_SOURCES = frozenset({ScoreSource.OPERATOR_VIDEO, ScoreSource.IMPORTED_LABEL})
AGREEMENT_COLUMNS = (
    "trial_id",
    "scorer_a",
    "outcome_a",
    "scorer_b",
    "outcome_b",
    "rubric_version",
    "notes",
)


def list_unscored(service: EvalService, session_id: str) -> list[TrialRecord]:
    """COMPLETED trials still awaiting a score (only these can be scored)."""
    return [
        t
        for t in service.list_trials(session_id, TrialState.COMPLETED)
        if t.task_outcome == TaskOutcome.UNSCORED
    ]


def _check_common(
    outcome: TaskOutcome,
    intervention: Intervention | None,
    who: str,
    source: ScoreSource,
    rubric_version: str,
) -> None:
    if not who or not who.strip():
        raise ValueError("a scorer/editor name is required")
    if TaskOutcome(outcome) == TaskOutcome.UNSCORED:
        raise ValueError("choose success or failure (a score cannot be 'unscored')")
    if intervention is None or Intervention(intervention) == Intervention.UNKNOWN:
        raise ValueError("intervention must be stated explicitly as 'none' or 'assisted' by the scorer")
    if source not in HUMAN_SOURCES:
        raise ValueError(f"scoring.py is for human scoring; source must be one of {sorted(HUMAN_SOURCES)}")
    if rubric_version != RUBRIC_VERSION:
        raise ValueError(
            f"unsupported rubric version {rubric_version!r}; this build implements {RUBRIC_VERSION}"
        )


def apply_score(
    service: EvalService,
    trial_id: str,
    outcome: TaskOutcome,
    *,
    scorer: str,
    intervention: Intervention,
    source: ScoreSource = ScoreSource.OPERATOR_VIDEO,
    rubric_version: str = RUBRIC_VERSION,
) -> TrialRecord:
    """First score of a COMPLETED trial. Raises ScoreProtectionError if already scored."""
    _check_common(outcome, intervention, scorer, source, rubric_version)
    trial = service.score_trial(trial_id, outcome, source=source, scorer=scorer, intervention=intervention)
    service.record_event(
        "score_rubric",
        trial.session_id,
        trial_id,
        scorer=scorer,
        rubric_version=rubric_version,
        intervention=Intervention(intervention).value,
    )
    return trial


def edit_score(
    service: EvalService,
    trial_id: str,
    outcome: TaskOutcome,
    *,
    editor: str,
    reason: str,
    intervention: Intervention,
    source: ScoreSource = ScoreSource.OPERATOR_VIDEO,
    rubric_version: str = RUBRIC_VERSION,
) -> ScoreEdit:
    """Audited change of an existing score; a non-empty reason is mandatory."""
    if not reason or not reason.strip():
        raise ValueError("edit_score requires a non-empty reason")
    _check_common(outcome, intervention, editor, source, rubric_version)
    edit = service.edit_score(
        trial_id, outcome, intervention=intervention, source=source, editor=editor, reason=reason
    )
    trial = service.get_trial(trial_id)
    service.record_event(
        "score_rubric", trial.session_id, trial_id, scorer=editor, rubric_version=rubric_version, edit=True
    )
    return edit


def score_history(service: EvalService, trial_id: str) -> list[ScoreEdit]:
    return service.list_score_edits(trial_id)


# --------------------------------------------------------------------------- agreement


class AgreementResult(BaseModel):
    n: int
    agreements: int
    percent_agreement: float | None
    cohen_kappa: float | None
    expected_agreement: float | None
    confusion: dict[str, int]  # "a:b" -> count
    note: str


def scoring_agreement(a_scores: Sequence[str], b_scores: Sequence[str]) -> AgreementResult:
    """Percent agreement and Cohen's kappa for two scorers' labels on the same items (same order).

    kappa = (po - pe) / (1 - pe), po = observed agreement, pe = sum over labels of P_a(l) * P_b(l).
    kappa is None when n == 0 or pe == 1 (undefined).
    """
    if len(a_scores) != len(b_scores):
        raise ValueError(f"score lists differ in length ({len(a_scores)} vs {len(b_scores)})")
    n = len(a_scores)
    conf: dict[str, int] = {}
    for x, y in zip(a_scores, b_scores, strict=True):
        conf[f"{x}:{y}"] = conf.get(f"{x}:{y}", 0) + 1
    if n == 0:
        return AgreementResult(
            n=0,
            agreements=0,
            percent_agreement=None,
            cohen_kappa=None,
            expected_agreement=None,
            confusion={},
            note="no paired scores: agreement is undefined (nothing was measured).",
        )
    agree = sum(1 for x, y in zip(a_scores, b_scores, strict=True) if x == y)
    po = agree / n
    labels = set(a_scores) | set(b_scores)
    pe = sum((a_scores.count(lbl) / n) * (b_scores.count(lbl) / n) for lbl in labels)
    kappa = None if abs(1 - pe) < 1e-12 else (po - pe) / (1 - pe)
    note = f"computed from {n} paired score(s) by two independent scorers."
    if kappa is None:
        note += " kappa undefined: expected agreement is 1 (a single label used by both)."
    if n < 30:
        note += " Small n: treat the estimate as indicative only."
    return AgreementResult(
        n=n,
        agreements=agree,
        percent_agreement=po,
        cohen_kappa=kappa,
        expected_agreement=pe,
        confusion=dict(sorted(conf.items())),
        note=note,
    )


def load_agreement_csv(path: str | Path) -> tuple[list[str], list[str], list[str]]:
    """Read docs/templates/scoring-agreement.csv format. Rows lacking either scorer's label are skipped and
    reported by the caller via the returned trial ids (ids are of USED rows). Returns (ids, a, b)."""
    ids: list[str] = []
    a: list[str] = []
    b: list[str] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = set(AGREEMENT_COLUMNS[:5]) - set(reader.fieldnames or [])
        if missing:
            raise RobotEvalOpsError(
                f"{path}: missing column(s) {sorted(missing)}; expected {AGREEMENT_COLUMNS}"
            )
        for row in reader:
            oa, ob = (row["outcome_a"] or "").strip().lower(), (row["outcome_b"] or "").strip().lower()
            if not oa or not ob:
                continue
            for lab in (oa, ob):
                if lab not in (TaskOutcome.SUCCESS.value, TaskOutcome.FAILURE.value):
                    raise RobotEvalOpsError(f"{path}: invalid outcome {lab!r}; use success or failure")
            if row["scorer_a"].strip().lower() == row["scorer_b"].strip().lower():
                raise RobotEvalOpsError(f"{path}: scorer_a and scorer_b must be different people")
            ids.append(row["trial_id"])
            a.append(oa)
            b.append(ob)
    return ids, a, b


def agreement_from_csv(path: str | Path) -> AgreementResult:
    _, a, b = load_agreement_csv(path)
    return scoring_agreement(a, b)
