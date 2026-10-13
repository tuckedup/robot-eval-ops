"""Quarantine: COPY offending artifacts to runs/<session>/quarantine/<trial_id>/ with an index.

Originals are never moved, modified or deleted. Status QUARANTINED is applied to the returned
report/refs only (the caller decides what to persist).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from robotevalops.schemas import ArtifactRef, ArtifactRole, ArtifactStatus, QAReport, Severity
from robotevalops.util import atomic_write_text, safe_relpath, sha256_file, utcnow


def offending_relpaths(report: QAReport, errors_only: bool = True) -> list[str]:
    out: list[str] = []
    for f in report.flags:
        if errors_only and f.severity != Severity.ERROR:
            continue
        rp = f.evidence.get("relpath")
        if isinstance(rp, str) and rp not in out:
            out.append(rp)
    return out


def quarantine_trial(
    run_dir: str | Path, trial_id: str, report: QAReport, errors_only: bool = True
) -> tuple[QAReport, list[ArtifactRef]]:
    """Copy each existing offending artifact into quarantine/<trial_id>/<relpath>. Returns a new
    report with `quarantined` set and ArtifactRefs with status QUARANTINED. Missing files are
    listed in the index as 'absent' (nothing to copy)."""
    root = Path(run_dir)
    qdir = root / "quarantine" / trial_id
    qdir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []
    refs: list[ArtifactRef] = []
    done: list[str] = []
    for rel in offending_relpaths(report, errors_only):
        rel = safe_relpath(rel)
        src = root / rel
        codes = sorted({f.code.value for f in report.flags if f.evidence.get("relpath") == rel})
        if not src.is_file():
            entries.append({"relpath": rel, "copy": None, "codes": codes, "note": "absent; nothing to copy"})
            continue
        digest = sha256_file(src)
        dest = qdir / rel
        if dest.exists() and sha256_file(dest) != digest:
            dest = dest.with_name(f"{dest.name}.{digest[:8]}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copy2(src, dest)
        entries.append(
            {
                "relpath": rel,
                "copy": dest.relative_to(root).as_posix(),
                "sha256": digest,
                "size_bytes": src.stat().st_size,
                "codes": codes,
            }
        )
        refs.append(
            ArtifactRef(
                role=ArtifactRole.OTHER,
                relpath=rel,
                sha256=digest,
                size_bytes=src.stat().st_size,
                status=ArtifactStatus.QUARANTINED,
                detail="copy in quarantine/" + trial_id + "; original untouched",
            )
        )
        done.append(rel)
    index = {
        "trial_id": trial_id,
        "created_at": utcnow().isoformat(),
        "policy": "copy-only",
        "flags": [f.model_dump(mode="json") for f in report.flags],
        "artifacts": entries,
    }
    atomic_write_text(qdir / "index.json", json.dumps(index, indent=2, default=str) + "\n")
    out = report.model_copy(deep=True)
    out.quarantined = done
    return out, refs
