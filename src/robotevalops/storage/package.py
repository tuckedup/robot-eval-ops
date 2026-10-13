"""Package / upload / download / verify a run directory (runs/<session_id>/).

Only regular files physically inside the run dir are collected. Symlinks, credential-looking files
(util.check_not_forbidden), temp files and the transfer-state directory are blocked and REPORTED.
Upload is resumable and idempotent via an atomic state file at <run_dir>/.transfer/upload_state.json.
Checksum agreement = verified / transferred.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from robotevalops.errors import (
    ArtifactOverwriteError,
    PathTraversalError,
    RobotEvalOpsError,
    TransferTimeoutError,
)
from robotevalops.schemas import ArtifactStatus
from robotevalops.storage.base import ArtifactStore
from robotevalops.storage.local import credential_reason, strict_key
from robotevalops.util import atomic_write_text, safe_relpath, sha256_file, utcnow

STATE_DIR = ".transfer"
STATE_NAME = "upload_state.json"
_TRANSFERRED = {ArtifactStatus.UPLOADED, ArtifactStatus.VERIFIED, ArtifactStatus.MISMATCH}


def run_prefix(session_id: str) -> str:
    return f"runs/{safe_relpath(session_id)}/"


@dataclass
class PackagedArtifact:
    relpath: str
    sha256: str | None
    size_bytes: int | None
    status: str  # ArtifactStatus value
    attempts: int = 0
    detail: str = ""


@dataclass
class PackageReport:
    session_id: str
    run_dir: str
    artifacts: list[PackagedArtifact] = field(default_factory=list)
    blocked: list[dict[str, str]] = field(default_factory=list)  # {relpath, reason}
    skipped_identical: int = 0
    errors: list[str] = field(default_factory=list)

    def count(self, *statuses: ArtifactStatus) -> int:
        vals = {s.value for s in statuses}
        return sum(1 for a in self.artifacts if a.status in vals)

    @property
    def transferred(self) -> int:
        return self.count(*_TRANSFERRED)

    @property
    def verified(self) -> int:
        return self.count(ArtifactStatus.VERIFIED)

    @property
    def checksum_agreement(self) -> float | None:
        """verified / transferred; None when nothing was transferred (never reported as 1.0)."""
        return self.verified / self.transferred if self.transferred else None

    @property
    def ok(self) -> bool:
        return not self.errors and not self.count(ArtifactStatus.FAILED, ArtifactStatus.MISMATCH)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.update(
            transferred=self.transferred,
            verified=self.verified,
            checksum_agreement=self.checksum_agreement,
            ok=self.ok,
        )
        return d


# --------------------------------------------------------------------------- collection


def collect_run_files(run_dir: str | Path) -> tuple[list[str], list[dict[str, str]]]:
    """Return (sorted safe relpaths, blocked list). Never follows symlinks."""
    root = Path(run_dir).resolve()
    files: list[str] = []
    blocked: list[dict[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dp = Path(dirpath)
        for d in list(dirnames):
            full = dp / d
            rel = full.relative_to(root).as_posix()
            if rel == STATE_DIR:
                dirnames.remove(d)
            elif full.is_symlink():
                blocked.append({"relpath": rel, "reason": "symlinked directory not followed"})
                dirnames.remove(d)
            elif credential_reason(rel + "/x") is not None:
                blocked.append({"relpath": rel, "reason": f"credential/VCS directory {d!r} not collected"})
                dirnames.remove(d)
        for name in filenames:
            full = dp / name
            rel = full.relative_to(root).as_posix()
            if name.endswith(".tmp"):
                blocked.append({"relpath": rel, "reason": "temporary file"})
                continue
            if full.is_symlink():
                blocked.append({"relpath": rel, "reason": "symlink (may escape the run directory)"})
                continue
            reason = credential_reason(rel)
            if reason is not None:
                blocked.append({"relpath": rel, "reason": reason})
                continue
            if root not in full.resolve().parents:
                blocked.append({"relpath": rel, "reason": "resolves outside the run directory"})
                continue
            files.append(rel)
    return sorted(files), sorted(blocked, key=lambda b: b["relpath"])


def build_package(run_dir: str | Path, session_id: str) -> PackageReport:
    """Artifact manifest of everything collectable (status PRESENT, sha256 + size recorded)."""
    root = Path(run_dir).resolve()
    files, blocked = collect_run_files(root)
    rep = PackageReport(session_id=session_id, run_dir=str(root), blocked=blocked)
    for rel in files:
        p = root / rel
        rep.artifacts.append(
            PackagedArtifact(rel, sha256_file(p), p.stat().st_size, ArtifactStatus.PRESENT.value)
        )
    return rep


# --------------------------------------------------------------------------- state


def _state_path(run_dir: Path) -> Path:
    return run_dir / STATE_DIR / STATE_NAME


def load_state(run_dir: str | Path) -> dict[str, dict[str, Any]]:
    p = _state_path(Path(run_dir))
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        arts = data.get("artifacts", {})
        return arts if isinstance(arts, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}  # corrupt state is ignored: uploads are idempotent at the store


def _save_state(run_dir: Path, session_id: str, rep: PackageReport) -> None:
    payload = {
        "session_id": session_id,
        "updated_at": utcnow().isoformat(),
        "artifacts": {a.relpath: asdict(a) for a in rep.artifacts},
    }
    atomic_write_text(_state_path(run_dir), json.dumps(payload, indent=2) + "\n")


# --------------------------------------------------------------------------- upload / verify / download


def _store_has(store: ArtifactStore, key: str, size: int | None) -> bool:
    """Resume state is only a hint: the object must still exist in the store with the same size."""
    try:
        return store.exists(key) and (size is None or store.stat(key).size_bytes == size)
    except (RobotEvalOpsError, OSError):
        return False


def upload_run(store: ArtifactStore, run_dir: str | Path, session_id: str) -> PackageReport:
    """Upload every collectable file to runs/<session_id>/<relpath>. Per-artifact failures are recorded
    (status FAILED, detail) and the remaining artifacts are still attempted; state is saved after each
    artifact so a re-run resumes and skips already-uploaded identical artifacts."""
    root = Path(run_dir).resolve()
    prefix = run_prefix(session_id)
    rep = build_package(root, session_id)
    state = load_state(root)
    pending: list[PackagedArtifact] = []
    for a in rep.artifacts:  # apply resume state first so every saved snapshot is complete
        prev = state.get(a.relpath)
        if (
            prev
            and prev.get("sha256") == a.sha256
            and prev.get("status") in (ArtifactStatus.UPLOADED.value, ArtifactStatus.VERIFIED.value)
            and _store_has(store, prefix + a.relpath, a.size_bytes)
        ):
            a.status = str(prev["status"])
            a.detail = "skipped: already uploaded with identical sha256 (resume state, store confirmed)"
            rep.skipped_identical += 1
            continue
        pending.append(a)  # state absent, stale, or the store no longer has the object: (re-)upload
    for a in pending:
        try:
            res = store.put_file(root / a.relpath, prefix + a.relpath, a.sha256)
            a.status = res.status.value
            a.attempts = res.attempts
            a.detail = res.detail
            if res.skipped_identical:
                rep.skipped_identical += 1
        except TransferTimeoutError as exc:
            a.status, a.detail = ArtifactStatus.FAILED.value, f"transfer timeout: {exc}"
            a.attempts = int(getattr(exc, "attempts", 0))
            rep.errors.append(f"{a.relpath}: {exc}")
        except ArtifactOverwriteError as exc:
            a.status, a.detail = ArtifactStatus.FAILED.value, f"overwrite refused: {exc}"
            rep.errors.append(f"{a.relpath}: {exc}")
        except (RobotEvalOpsError, OSError) as exc:
            a.status, a.detail = ArtifactStatus.FAILED.value, f"{type(exc).__name__}: {exc}"
            rep.errors.append(f"{a.relpath}: {exc}")
        _save_state(root, session_id, rep)
    return rep


def verify_run(
    store: ArtifactStore, run_dir: str | Path, session_id: str, scratch_dir: str | Path | None = None
) -> PackageReport:
    """Download + recompute SHA-256 for every local artifact (never trusts size/ETag/state)."""
    root = Path(run_dir).resolve()
    scratch = Path(scratch_dir) if scratch_dir else root / STATE_DIR / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    prefix = run_prefix(session_id)
    rep = build_package(root, session_id)
    for a in rep.artifacts:
        assert a.sha256 is not None
        try:
            res = store.verify(prefix + a.relpath, a.sha256, scratch)
            a.status, a.detail, a.attempts = res.status.value, res.detail, res.attempts
        except TransferTimeoutError as exc:
            a.status, a.detail = ArtifactStatus.FAILED.value, f"transfer timeout: {exc}"
            rep.errors.append(f"{a.relpath}: {exc}")
        except (RobotEvalOpsError, OSError) as exc:
            a.status, a.detail = ArtifactStatus.FAILED.value, f"{type(exc).__name__}: {exc}"
            rep.errors.append(f"{a.relpath}: {exc}")
        if a.status == ArtifactStatus.MISMATCH.value:
            rep.errors.append(f"{a.relpath}: checksum mismatch ({a.detail})")
    _save_state(root, session_id, rep)
    return rep


def download_run(store: ArtifactStore, session_id: str, dest_dir: str | Path) -> PackageReport:
    """Download runs/<session_id>/* into dest_dir. Store keys are re-validated (a hostile key such as
    '../x' is blocked). If the store recorded a sha256 it is recomputed after download -> VERIFIED/MISMATCH;
    otherwise the file is PRESENT with sha256 computed locally. Identical existing files are kept."""
    dest = Path(dest_dir).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    prefix = run_prefix(session_id)
    rep = PackageReport(session_id=session_id, run_dir=str(dest))
    for obj in store.list(prefix):
        rel = obj.key[len(prefix) :]
        try:
            rel = strict_key(rel)
        except PathTraversalError as exc:
            rep.blocked.append({"relpath": rel, "reason": str(exc)})
            continue
        target = dest / rel
        if dest not in target.resolve().parents:
            rep.blocked.append({"relpath": rel, "reason": "resolves outside destination"})
            continue
        try:
            if target.is_file() and obj.sha256 and sha256_file(target) == obj.sha256:
                rep.skipped_identical += 1
            else:
                store.get_file(obj.key, target)
            actual = sha256_file(target)
            if obj.sha256 is None:
                status, detail = ArtifactStatus.PRESENT, "store recorded no sha256; hash computed locally"
            elif actual == obj.sha256:
                status, detail = ArtifactStatus.VERIFIED, ""
            else:
                status, detail = (
                    ArtifactStatus.MISMATCH,
                    f"downloaded {actual[:12]}... != recorded {obj.sha256[:12]}...",
                )
                rep.errors.append(f"{rel}: {detail}")
            rep.artifacts.append(
                PackagedArtifact(rel, actual, target.stat().st_size, status.value, detail=detail)
            )
        except (RobotEvalOpsError, OSError) as exc:
            rep.artifacts.append(
                PackagedArtifact(rel, None, None, ArtifactStatus.FAILED.value, detail=str(exc))
            )
            rep.errors.append(f"{rel}: {exc}")
    return rep
