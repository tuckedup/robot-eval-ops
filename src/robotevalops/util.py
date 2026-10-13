"""Shared low-level helpers (lead-owned). Pure functions, no domain state."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import platform
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from robotevalops.errors import PathTraversalError

SCHEMA_VERSION = "1.0"
RUBRIC_VERSION = "rubric-v1"

# File names/patterns that must never be collected into an artifact package.
FORBIDDEN_NAMES = {".env", "credentials", "config.json", "id_rsa", "id_ed25519", ".netrc", ".pgpass"}
FORBIDDEN_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".kdbx"}
FORBIDDEN_PARTS = {".aws", ".ssh", ".git", ".gnupg"}


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def new_id() -> str:
    """UUID4 string used for session/trial identifiers."""
    return str(uuid.uuid4())


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def canonical_json(obj: Any) -> str:
    """Deterministic JSON (sorted keys, no whitespace) for hashing configs."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def config_hash(obj: Any) -> str:
    return sha256_bytes(canonical_json(obj).encode("utf-8"))


def derive_seed(base_seed: int, condition_name: str, trial_index: int) -> int:
    """Seed for a (condition, trial_index) cell.

    Deliberately independent of controller identity so every controller sees the
    same seed/condition schedule (paired design).
    """
    digest = hashlib.sha256(f"{base_seed}|{condition_name}|{trial_index}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def atomic_write_bytes(path: str | Path, data: bytes) -> None:
    """Write via temp file + os.replace so readers never see partial content."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def atomic_write_text(path: str | Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def safe_relpath(rel: str) -> str:
    """Validate a relative POSIX artifact path. Raises PathTraversalError if unsafe."""
    if not rel or "\\" in rel or "\x00" in rel:
        raise PathTraversalError(f"invalid artifact path {rel!r}: must be non-empty POSIX relative")
    p = PurePosixPath(rel)
    segments = rel.split("/")  # PurePosixPath silently drops "." and "//", so check raw segments
    if p.is_absolute() or (len(rel) > 1 and rel[1] == ":") or any(seg in ("", ".", "..") for seg in segments):
        raise PathTraversalError(f"artifact path {rel!r} must be relative without '.'/'..' segments")
    check_not_forbidden(p)
    return p.as_posix()


def check_not_forbidden(p: PurePosixPath | Path) -> None:
    parts = {x.lower() for x in p.parts}
    name = p.name.lower()
    if parts & FORBIDDEN_PARTS or name in FORBIDDEN_NAMES or name.endswith(tuple(FORBIDDEN_SUFFIXES)):
        raise PathTraversalError(f"refusing to collect credential/unrelated file: {p.as_posix()}")


def resolve_within(root: str | Path, rel: str) -> Path:
    """Resolve rel under root, guaranteeing the result stays inside root (symlinks included)."""
    root_p = Path(root).resolve()
    target = (root_p / safe_relpath(rel)).resolve()
    if root_p != target and root_p not in target.parents:
        raise PathTraversalError(f"{rel!r} resolves outside {root_p}")
    return target


def get_home(explicit: str | Path | None = None) -> Path:
    """Data root: explicit arg > $ROBOTEVALOPS_HOME > ./data (gitignored)."""
    return Path(explicit or os.environ.get("ROBOTEVALOPS_HOME") or "data").resolve()


def git_commit(cwd: str | Path | None = None) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True, timeout=5, check=False
        )
        return out.stdout.strip() or None if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def software_versions() -> dict[str, str]:
    """Versions of the interpreter and optional libs that are importable (never imports lerobot eagerly)."""
    from importlib import metadata

    vers = {"python": sys.version.split()[0], "platform": platform.platform()}
    for pkg in (
        "robotevalops",
        "numpy",
        "pandas",
        "pydantic",
        "pybullet",
        "opencv-python-headless",
        "boto3",
        "streamlit",
        "lerobot",
        "torch",
    ):
        with contextlib.suppress(metadata.PackageNotFoundError):
            vers[pkg] = metadata.version(pkg)
    return vers


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def get_logger(name: str, log_file: str | Path | None = None) -> logging.Logger:
    """Structured JSON logger. Pass fields via logger.info("msg", extra={"fields": {...}})."""
    logger = logging.getLogger(name)
    if not any(getattr(h, "_roe", False) for h in logger.handlers):
        handler: logging.Handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(_JsonFormatter())
        handler._roe = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    if log_file is not None:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        key = str(Path(log_file).resolve())
        if not any(getattr(h, "_roe_file", None) == key for h in logger.handlers):
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setFormatter(_JsonFormatter())
            fh._roe_file = key  # type: ignore[attr-defined]
            logger.addHandler(fh)
    return logger
