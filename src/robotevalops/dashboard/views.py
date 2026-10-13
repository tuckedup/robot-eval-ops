"""Pure view-model functions for the dashboard (no Streamlit import): testable without a browser.

Only the public EvalService API is used. Nothing here can move a robot.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from robotevalops.core.service import EvalService
from robotevalops.errors import NotFoundError, PathTraversalError
from robotevalops.metrics.compare import Comparison, compare_controllers
from robotevalops.metrics.compute import MetricsReport, compute_metrics
from robotevalops.metrics.failures import FailureReport, failure_report
from robotevalops.reporting.data import PROVENANCE_NOTES, SessionBundle, load_bundles, trial_rows
from robotevalops.schemas import ArtifactRole, TrialRecord
from robotevalops.util import resolve_within

SESSION_COLUMNS = [
    "session_id",
    "name",
    "state",
    "provenance",
    "backend",
    "purpose",
    "operator",
    "planned_trials",
    "created_at",
]


def session_table(service: EvalService) -> pd.DataFrame:
    rows = []
    for s in service.list_sessions():
        rows.append(
            {
                "session_id": s.session_id,
                "name": s.name,
                "state": s.state.value,
                "provenance": s.provenance.value,
                "backend": s.backend,
                "purpose": s.purpose,
                "operator": s.operator,
                "planned_trials": len(service.list_trials(s.session_id)),
                "created_at": s.created_at.isoformat(),
            }
        )
    return pd.DataFrame(rows, columns=SESSION_COLUMNS)


def banners(provenances: Sequence[str]) -> list[str]:
    """Banner strings that must be shown prominently for these provenance values."""
    return [PROVENANCE_NOTES[p] for p in provenances if p in PROVENANCE_NOTES]


def session_banners(bundle: SessionBundle) -> list[str]:
    ctypes = sorted({t.controller_type.value for t in bundle.trials})
    out = banners([bundle.session.provenance.value])
    if ctypes:
        out.append(
            "Controller type(s): " + ", ".join(ctypes) + " (a scripted config is not a learned checkpoint)"
        )
    return out


def trial_table(
    service: EvalService,
    session_id: str,
    *,
    controller: str | None = None,
    condition: str | None = None,
    state: str | None = None,
) -> pd.DataFrame:
    bundle = load_bundles(service, [session_id])[0]
    df = pd.DataFrame(trial_rows([bundle]))
    if df.empty:
        return df
    if controller:
        df = df[df["controller_id"] == controller]
    if condition:
        df = df[df["condition"] == condition]
    if state:
        df = df[df["state"] == state]
    return df.reset_index(drop=True)


def metrics_for(service: EvalService, session_ids: Sequence[str]) -> MetricsReport:
    trials: list[TrialRecord] = []
    for sid in session_ids:
        trials += service.list_trials(sid)
    return compute_metrics(trials)


def metrics_frame(report: MetricsReport) -> pd.DataFrame:
    rows = []
    for g in report.by_controller_condition:
        rows.append(
            {
                **g.key,
                "planned": g.planned,
                "attempted": g.attempted,
                "completed": g.completed,
                "failed": g.failed,
                "aborted": g.aborted,
                "unscored": g.unscored,
                "evaluable": g.evaluable,
                "success/attempted": g.success_per_attempt.fmt(),
                "success/evaluable": g.success_per_evaluable.fmt(),
                "intervention rate": g.intervention_rate.fmt(),
                "infra-abort rate": g.infra_abort_rate.fmt(),
                "recording pass rate": g.recording_pass_rate.fmt(),
            }
        )
    return pd.DataFrame(rows)


def condition_comparison(
    service: EvalService, session_ids: Sequence[str], controller_a: str, controller_b: str
) -> tuple[Comparison, pd.DataFrame]:
    trials: list[TrialRecord] = []
    for sid in session_ids:
        trials += service.list_trials(sid)
    cmp = compare_controllers(trials, controller_a, controller_b)
    df = pd.DataFrame(
        [
            {
                "condition": c.condition,
                "pairs": c.pairs,
                "both": c.both,
                "A only": c.a_only,
                "B only": c.b_only,
                "neither": c.neither,
                "A success": c.a_success.fmt(),
                "B success": c.b_success.fmt(),
                "exact McNemar p": None
                if c.p_value_exact_mcnemar is None
                else round(c.p_value_exact_mcnemar, 4),
            }
            for c in [cmp.overall, *cmp.by_condition]
        ]
    )
    return cmp, df


def failure_frame(service: EvalService, session_ids: Sequence[str]) -> tuple[FailureReport, pd.DataFrame]:
    trials: list[TrialRecord] = []
    for sid in session_ids:
        trials += service.list_trials(sid)
    rep = failure_report(trials)
    return rep, pd.DataFrame([r.model_dump() for r in rep.rows])


def artifact_frame(trial: TrialRecord) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "role": a.role.value,
                "relpath": a.relpath,
                "status": a.status.value,
                "sha256": a.sha256 or "",
                "size_bytes": a.size_bytes,
                "detail": a.detail,
            }
            for a in trial.artifacts
        ],
        columns=["role", "relpath", "status", "sha256", "size_bytes", "detail"],
    )


def qa_frame(service: EvalService, session_id: str) -> pd.DataFrame:
    rows = []
    for t in service.list_trials(session_id):
        rows.append(
            {
                "trial_id": t.trial_id,
                "controller": t.controller_id,
                "condition": t.condition_name,
                "state": t.state.value,
                "recording_quality": t.recording_quality.value,
                "qa_flags": ";".join(t.qa_flags),
                "artifacts": len(t.artifacts),
                "artifacts_not_present": sum(
                    a.status.value in ("missing", "failed", "pending", "mismatch", "quarantined")
                    for a in t.artifacts
                ),
            }
        )
    return pd.DataFrame(rows)


def score_history_frame(service: EvalService, trial_id: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "at": e.at.isoformat(),
                "editor": e.editor,
                "reason": e.reason,
                "outcome": f"{e.before_outcome.value} -> {e.after_outcome.value}",
                "intervention": f"{e.before_intervention.value} -> {e.after_intervention.value}",
                "source": f"{e.before_source.value} -> {e.after_source.value}",
            }
            for e in service.list_score_edits(trial_id)
        ],
        columns=["at", "editor", "reason", "outcome", "intervention", "source"],
    )


def _artifact_path(
    service: EvalService, trial: TrialRecord, role: ArtifactRole, default_rel: str
) -> tuple[Path | None, str]:
    """Resolve an artifact inside the run dir. Returns (path, message); path None => message says why."""
    rel = next((a.relpath for a in trial.artifacts if a.role == role), None) or default_rel
    run_dir = service.run_dir(trial.session_id)
    try:
        path = resolve_within(run_dir, rel)
    except PathTraversalError as e:
        return None, f"refused unsafe artifact path: {e}"
    if not path.is_file():
        return None, f"missing artifact: {rel} is not on disk under runs/{trial.session_id}/"
    return path, ""


def resolve_trial_video(service: EvalService, trial: TrialRecord) -> tuple[Path | None, str]:
    return _artifact_path(service, trial, ArtifactRole.VIDEO, f"trials/{trial.trial_id}/video.mp4")


def read_trial_log(service: EvalService, trial: TrialRecord, max_lines: int = 200) -> tuple[list[str], str]:
    path, msg = _artifact_path(service, trial, ArtifactRole.LOG, f"trials/{trial.trial_id}/trial.log.jsonl")
    if path is None:
        return [], msg
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-max_lines:], ""


def get_trial_in_session(service: EvalService, session_id: str, trial_id: str) -> TrialRecord:
    t = service.get_trial(trial_id)
    if t.session_id != session_id:
        raise NotFoundError(f"trial {trial_id} does not belong to session {session_id}")
    return t


def trial_detail(trial: TrialRecord) -> str:
    return json.dumps(trial.model_dump(mode="json"), indent=2)
