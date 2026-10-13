"""Run manifest build/read/write/validate. manifest.json covers every planned trial.

Nothing here invents values: missing required fields are *reported*, never defaulted.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from robotevalops.errors import SchemaMismatchError
from robotevalops.schemas import (
    REQUIRED_FIELDS_BY_PROVENANCE,
    REQUIRED_IF_ATTEMPTED,
    ArtifactRole,
    ArtifactStatus,
    ControllerType,
    Provenance,
    QACode,
    QAFlag,
    RunManifest,
    Severity,
    TaskOutcome,
    TerminationReason,
    TrialManifestEntry,
    TrialState,
)
from robotevalops.util import SCHEMA_VERSION, atomic_write_text, sha256_file, utcnow

_TERMINAL = (TrialState.COMPLETED, TrialState.FAILED, TrialState.ABORTED)


def build_manifest(
    *,
    session_id: str,
    provenance: Provenance,
    backend: str,
    task_id: str,
    rubric_version: str,
    trials: list[TrialManifestEntry],
    git_commit: str | None = None,
    software: dict[str, str] | None = None,
    eval_config_hash: str | None = None,
    created_at: datetime | None = None,
) -> RunManifest:
    return RunManifest(
        session_id=session_id,
        provenance=provenance,
        backend=backend,
        task_id=task_id,
        rubric_version=rubric_version,
        git_commit=git_commit,
        software=software or {},
        eval_config_hash=eval_config_hash,
        created_at=created_at or utcnow(),
        trials=trials,
    )


def write_manifest(path: str | Path, manifest: RunManifest) -> None:
    """Atomic write (temp + os.replace)."""
    atomic_write_text(path, manifest.model_dump_json(indent=2) + "\n")


def read_manifest(path: str | Path) -> RunManifest:
    """Read manifest.json. Raises SchemaMismatchError on version mismatch or invalid structure."""
    raw: Any = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SchemaMismatchError(f"{path}: manifest must be a JSON object")
    ver = raw.get("schema_version")
    if ver != SCHEMA_VERSION:
        raise SchemaMismatchError(
            f"{path}: manifest schema_version {ver!r} != supported {SCHEMA_VERSION!r}; "
            "re-export the manifest with a matching RobotEvalOps version"
        )
    try:
        return RunManifest.model_validate(raw)
    except ValidationError as exc:
        raise SchemaMismatchError(f"{path}: manifest does not match the schema: {exc}") from exc


def refresh_artifact_hashes(manifest: RunManifest, run_dir: str | Path) -> RunManifest:
    """Return a copy where every artifact that exists under run_dir has sha256/size recorded
    (status PRESENT) and every absent one is MISSING. Call at recording time only: it overwrites
    recorded hashes, which QA otherwise compares against."""
    root = Path(run_dir)
    out = manifest.model_copy(deep=True)
    for t in out.trials:
        for a in t.artifacts:
            p = root / a.relpath
            if p.is_file():
                a.sha256 = sha256_file(p)
                a.size_bytes = p.stat().st_size
                a.status = ArtifactStatus.PRESENT
            else:
                a.status = ArtifactStatus.MISSING
    return out


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _attempted(entry: TrialManifestEntry) -> bool:
    return entry.state in _TERMINAL and entry.termination_reason != TerminationReason.NOT_RUN


def entry_missing_fields(entry: TrialManifestEntry) -> list[str]:
    """Exact names of required-but-absent fields for one entry (per its own provenance)."""
    missing = [f for f in REQUIRED_FIELDS_BY_PROVENANCE[entry.provenance] if _blank(getattr(entry, f))]
    if _attempted(entry):
        missing += [f for f in REQUIRED_IF_ATTEMPTED if _blank(getattr(entry, f))]
    if entry.controller_type == ControllerType.LEARNED:
        if _blank(entry.model_artifact_sha256):
            missing.append("model_artifact_sha256")
        if not any(a.role == ArtifactRole.MODEL for a in entry.artifacts):
            missing.append("artifacts[role=model]")
    return missing


def _required_count(entry: TrialManifestEntry) -> int:
    n = len(REQUIRED_FIELDS_BY_PROVENANCE[entry.provenance])
    if _attempted(entry):
        n += len(REQUIRED_IF_ATTEMPTED)
    if entry.controller_type == ControllerType.LEARNED:
        n += 2
    return n


def missing_required_fields(manifest: RunManifest) -> list[str]:
    """Exact list as 'trial_id:field', in manifest order."""
    return [f"{t.trial_id}:{f}" for t in manifest.trials for f in entry_missing_fields(t)]


def required_metadata_completeness(manifest: RunManifest) -> float:
    """Fraction of required metadata slots that are filled (1.0 when nothing is required).
    Physical calibration counts only for physical_hardware trials. The exact list of
    missing fields is `missing_required_fields(manifest)`."""
    total = sum(_required_count(t) for t in manifest.trials)
    if total == 0:
        return 1.0
    missing = sum(len(entry_missing_fields(t)) for t in manifest.trials)
    return (total - missing) / total


def entry_completeness(entry: TrialManifestEntry) -> float:
    total = _required_count(entry)
    return (total - len(entry_missing_fields(entry))) / total


def entry_flags(entry: TrialManifestEntry) -> list[QAFlag]:
    flags: list[QAFlag] = []
    for f in entry_missing_fields(entry):
        if f == "artifacts[role=model]":
            flags.append(
                QAFlag(
                    code=QACode.MISSING_MODEL_ARTIFACT,
                    severity=Severity.ERROR,
                    subject=entry.trial_id,
                    message=f"trial {entry.trial_id} uses a learned controller but lists no MODEL artifact; "
                    "attach the checkpoint artifact (with sha256) or relabel the controller",
                    evidence={"field": f},
                )
            )
        else:
            flags.append(
                QAFlag(
                    code=QACode.MISSING_FIELD,
                    severity=Severity.ERROR,
                    subject=entry.trial_id,
                    message=f"trial {entry.trial_id}: required field {f!r} is missing for provenance "
                    f"{entry.provenance.value}; record it (never guess a value)",
                    evidence={"field": f},
                )
            )
    return flags


def validate_manifest(manifest: RunManifest) -> list[QAFlag]:
    """Manifest-level QA flags: schema version, duplicate trial ids, missing fields, model artifact,
    missing outcome labels."""
    flags: list[QAFlag] = []
    if manifest.schema_version != SCHEMA_VERSION:
        flags.append(
            QAFlag(
                code=QACode.SCHEMA_MISMATCH,
                severity=Severity.ERROR,
                subject="manifest.json",
                message=f"manifest schema_version {manifest.schema_version!r} != {SCHEMA_VERSION!r}; "
                "re-export with a matching version",
                evidence={"found": manifest.schema_version, "expected": SCHEMA_VERSION},
            )
        )
    seen: dict[str, int] = {}
    for t in manifest.trials:
        seen[t.trial_id] = seen.get(t.trial_id, 0) + 1
    for tid, n in seen.items():
        if n > 1:
            flags.append(
                QAFlag(
                    code=QACode.DUPLICATE_ID,
                    severity=Severity.ERROR,
                    subject=tid,
                    message=f"trial_id {tid!r} appears {n} times in manifest.json; trial ids must be unique "
                    "- find the colliding records and re-issue ids (do not delete either record)",
                    evidence={"trial_id": tid, "count": n},
                )
            )
    for t in manifest.trials:
        flags.extend(entry_flags(t))
        if t.state == TrialState.COMPLETED and t.task_outcome == TaskOutcome.UNSCORED:
            flags.append(
                QAFlag(
                    code=QACode.MISSING_OUTCOME,
                    severity=Severity.WARNING,
                    subject=t.trial_id,
                    message=f"trial {t.trial_id} completed but has no outcome label; score it from "
                    "physics evidence or operator video review",
                )
            )
    return flags
