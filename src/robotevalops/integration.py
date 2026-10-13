"""Glue between storage transfer reports and the core database (lead-owned).

Transfer/verify results live in a PackageReport; metrics read ArtifactRef.status from the DB. This copies the
per-artifact status (uploaded/verified/mismatch/failed) back so reports show real checksum counts.
Only artifacts already registered on a trial are updated; statuses are never upgraded without a report entry.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from robotevalops.core.service import EvalService
from robotevalops.schemas import ArtifactRef, ArtifactStatus, QAReport, TrialRecord
from robotevalops.storage.package import PackageReport
from robotevalops.util import atomic_write_text


def apply_transfer_report(svc: EvalService, session_id: str, report: PackageReport) -> int:
    """Return the number of trial artifacts whose status was updated."""
    by_rel = {a.relpath: a for a in report.artifacts}
    updated = 0
    for trial in svc.list_trials(session_id):
        refs: list[ArtifactRef] = []
        for art in trial.artifacts:
            pa = by_rel.get(art.relpath)
            if pa is None:
                continue
            refs.append(
                art.model_copy(
                    update={
                        "status": ArtifactStatus(pa.status),
                        "sha256": pa.sha256 or art.sha256,
                        "detail": pa.detail or art.detail,
                    }
                )
            )
        if refs:
            svc.register_artifacts(trial.trial_id, refs)
            updated += len(refs)
    return updated


def make_hooks(
    svc: EvalService,
) -> tuple[Callable[[TrialRecord, Path], QAReport], Callable[[str], None]]:
    """(qa_hook, manifest_hook) for `Runner`. Every runner entry point (CLI `session run`, demo) must use
    these so recording QA always reaches the database: a corrupt recording can never stay `unchecked`
    and be counted as evaluable."""
    from robotevalops.qa.trial_qa import qa_trial
    from robotevalops.recording.manifest import write_manifest

    def qa_hook(trial: TrialRecord, run_dir: Path) -> QAReport:
        manifest = svc.export_manifest(trial.session_id)
        entry = next(e for e in manifest.trials if e.trial_id == trial.trial_id)
        report = qa_trial(run_dir, entry)
        atomic_write_text(run_dir / "qa" / f"{trial.trial_id}.qa.json", report.model_dump_json(indent=2))
        return report

    def manifest_hook(session_id: str) -> None:
        write_manifest(svc.run_dir(session_id) / "manifest.json", svc.export_manifest(session_id))

    return qa_hook, manifest_hook
