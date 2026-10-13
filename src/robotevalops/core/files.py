"""Filesystem helpers shared by the Runner and crash recovery (hash + register what is really on disk)."""

from __future__ import annotations

from pathlib import Path

from robotevalops.schemas import ArtifactRef, ArtifactRole, ArtifactStatus
from robotevalops.util import sha256_file


def role_for(name: str) -> ArtifactRole:
    n = name.lower()
    if n.endswith((".mp4", ".webm", ".avi")):
        return ArtifactRole.VIDEO
    if n == "trace.jsonl" or n.endswith(".trace.jsonl"):
        return ArtifactRole.TRACE
    if n.endswith(".log.jsonl") or n.endswith(".log"):
        return ArtifactRole.LOG
    if n == "controller.json":
        return ArtifactRole.CONFIG
    return ArtifactRole.OTHER


def describe_file(session_dir: Path, path: Path, role: ArtifactRole | None = None) -> ArtifactRef:
    """ArtifactRef for an existing file: relpath is POSIX relative to `session_dir`, sha256/size measured."""
    rel = path.resolve().relative_to(session_dir.resolve()).as_posix()
    return ArtifactRef(
        role=role or role_for(path.name),
        relpath=rel,
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
        status=ArtifactStatus.PRESENT,
    )


def missing_ref(relpath: str, role: ArtifactRole, detail: str) -> ArtifactRef:
    return ArtifactRef(role=role, relpath=relpath, status=ArtifactStatus.MISSING, detail=detail)


def scan_dir(session_dir: Path, directory: Path) -> list[ArtifactRef]:
    """Every regular file under `directory` (sorted) as a PRESENT ArtifactRef. Temp files are included on
    purpose: after a crash they are evidence."""
    if not directory.is_dir():
        return []
    return [describe_file(session_dir, p) for p in sorted(directory.rglob("*")) if p.is_file()]
