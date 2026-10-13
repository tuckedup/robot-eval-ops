"""Glue between storage transfer reports and the core database (lead-owned).

Transfer/verify results live in a PackageReport; metrics read ArtifactRef.status from the DB. This copies the
per-artifact status (uploaded/verified/mismatch/failed) back so reports show real checksum-verification counts.
Only artifacts already registered on a trial are updated; statuses are never upgraded without a report entry.
"""

from __future__ import annotations

from robotevalops.core.service import EvalService
from robotevalops.schemas import ArtifactRef, ArtifactStatus
from robotevalops.storage.package import PackageReport


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
