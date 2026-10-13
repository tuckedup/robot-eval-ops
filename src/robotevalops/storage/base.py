"""Artifact-store interface (lead-owned contract). Implementations: LocalArtifactStore
(default, offline) and S3ArtifactStore (optional boto3; credential chain only)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from robotevalops.schemas import ArtifactStatus


@dataclass(frozen=True)
class StoredObject:
    key: str  # stable POSIX key, e.g. "runs/<session_id>/trials/<trial_id>/video.mp4"
    size_bytes: int
    sha256: str | None  # recorded SHA-256 (metadata/manifest). NEVER an S3 ETag.


@dataclass(frozen=True)
class TransferResult:
    key: str
    status: ArtifactStatus  # UPLOADED / VERIFIED / MISMATCH / FAILED
    sha256: str | None
    attempts: int
    skipped_identical: bool = False  # idempotent re-upload of identical bytes
    detail: str = ""


class ArtifactStore(ABC):
    @abstractmethod
    def put_file(self, local_path: Path, key: str, sha256: str | None = None) -> TransferResult:
        """Upload. Idempotent for identical bytes; raises ArtifactOverwriteError if the key
        holds DIFFERENT bytes. Bounded retries; raises TransferTimeoutError when exhausted."""

    @abstractmethod
    def get_file(self, key: str, dest: Path) -> Path:
        """Download atomically (temp + replace)."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def stat(self, key: str) -> StoredObject: ...

    @abstractmethod
    def list(self, prefix: str) -> list[StoredObject]: ...

    @abstractmethod
    def verify(self, key: str, expected_sha256: str, scratch_dir: Path) -> TransferResult:
        """Download and recompute SHA-256 (never trust size/ETag). MISMATCH on difference."""
