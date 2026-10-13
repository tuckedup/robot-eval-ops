"""Load sessions/trials/configs through the public EvalService API only (never SQL)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from robotevalops.core.service import EvalService
from robotevalops.metrics.compare import Comparison, compare_controllers
from robotevalops.metrics.compute import MetricsReport, compute_metrics
from robotevalops.metrics.failures import FailureReport, failure_class, failure_report
from robotevalops.schemas import ArtifactRole, EvalConfig, Provenance, SessionRecord, TrialRecord

PROVENANCE_NOTES = {
    Provenance.MOCK.value: "MOCK FIXTURE — not evidence of robotics performance",
    Provenance.SIMULATION.value: (
        "SIMULATION — PyBullet Panda arm with rendered simulator frames; not the SO-101 and not hardware"
    ),
    Provenance.IMPORTED_REAL_RECORDING.value: (
        "IMPORTED REAL RECORDING — recorded elsewhere; labels are imported, not produced by this repository"
    ),
    Provenance.PHYSICAL_HARDWARE.value: "PHYSICAL HARDWARE — real device; results depend on operator scoring",
}


@dataclass
class SessionBundle:
    session: SessionRecord
    eval_config: EvalConfig | None
    trials: list[TrialRecord]
    run_dir_rel: str
    manifest_exists: bool
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ReportData:
    bundles: list[SessionBundle]
    trials: list[TrialRecord]
    metrics: MetricsReport
    failures: FailureReport
    comparisons: list[Comparison]

    @property
    def provenances(self) -> list[str]:
        return self.metrics.provenances


def load_bundles(service: EvalService, session_ids: Sequence[str]) -> list[SessionBundle]:
    out = []
    for sid in session_ids:
        sess = service.get_session(sid)
        run_dir = service.run_dir(sid)
        out.append(
            SessionBundle(
                session=sess,
                eval_config=service.get_eval_config(sid),
                trials=service.list_trials(sid),
                run_dir_rel=f"runs/{sid}",
                manifest_exists=(run_dir / "manifest.json").is_file(),
                events=service.list_events(sid),
            )
        )
    return out


def build_report_data(service: EvalService, session_ids: Sequence[str]) -> ReportData:
    bundles = load_bundles(service, session_ids)
    trials = [t for b in bundles for t in b.trials]
    ids = sorted({t.controller_id for t in trials})
    comps = [compare_controllers(trials, a, b) for a, b in combinations(ids, 2)]
    return ReportData(bundles, trials, compute_metrics(trials), failure_report(trials), comps)


def trial_rows(bundles: Sequence[SessionBundle]) -> list[dict[str, Any]]:
    """One row per planned trial (including never-attempted ones)."""
    rows: list[dict[str, Any]] = []
    for b in bundles:
        for t in b.trials:
            video = next((a for a in t.artifacts if a.role == ArtifactRole.VIDEO), None)
            rows.append(
                {
                    "provenance_banner": PROVENANCE_NOTES.get(t.provenance.value, ""),
                    "session_id": t.session_id,
                    "trial_id": t.trial_id,
                    "schedule_position": t.schedule_position,
                    "provenance": t.provenance.value,
                    "backend": t.backend,
                    "controller_id": t.controller_id,
                    "controller_type": t.controller_type.value,
                    "controller_version": t.controller_version,
                    "controller_config_hash": t.controller_config_hash,
                    "condition": t.condition_name,
                    "condition_kind": t.condition_kind,
                    "trial_index": t.trial_index,
                    "seed": t.seed,
                    "state": t.state.value,
                    "attempted": t.is_attempted,
                    "termination_reason": t.termination_reason.value,
                    "task_outcome": t.task_outcome.value,
                    "score_source": t.score_source.value,
                    "rubric_version": t.rubric_version,
                    "intervention": t.intervention.value,
                    "recording_quality": t.recording_quality.value,
                    "autonomous_success": t.is_autonomous_success,
                    "failure_class": failure_class(t),
                    "duration_s": t.duration_s,
                    "reset_duration_s": t.reset_duration_s,
                    "qa_flags": ";".join(t.qa_flags),
                    "n_artifacts": len(t.artifacts),
                    "video_relpath": f"{b.run_dir_rel}/{video.relpath}" if video else "",
                    "video_status": video.status.value if video else "not_registered",
                    "manifest_path": f"{b.run_dir_rel}/manifest.json",
                }
            )
    return rows
