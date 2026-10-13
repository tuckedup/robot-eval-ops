"""LocalArtifactStore: filesystem store with the same key space as S3 (offline default).

Layout: <root>/<key> for objects; <root>/.meta/<key>.sha256 sidecar holding the recorded SHA-256
(written atomically after the object). Keys are validated with util.safe_relpath.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

from robotevalops.errors import (
    ArtifactIntegrityError,
    ArtifactOverwriteError,
    NotFoundError,
    PathTraversalError,
)
from robotevalops.schemas import ArtifactStatus
from robotevalops.storage.base import ArtifactStore, StoredObject, TransferResult
from robotevalops.util import atomic_write_text, safe_relpath, sha256_file

META_DIR = ".meta"


def strict_key(key: str) -> str:
    """util.safe_relpath plus canonical-form check: rejects 'a/./b', 'a//b' and trailing '/'
    (PurePosixPath silently normalises those, which safe_relpath cannot see)."""
    k = safe_relpath(key)
    if k != key:
        raise PathTraversalError(f"artifact key {key!r} is not canonical (expected {k!r})")
    return k


class LocalArtifactStore(ArtifactStore):
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # ---- helpers
    def _key(self, key: str) -> str:
        k = strict_key(key)
        if k.split("/", 1)[0] == META_DIR:
            raise PathTraversalError(f"key {key!r} uses the reserved {META_DIR!r} directory")
        return k

    def _path(self, key: str) -> Path:
        k = self._key(key)
        p = (self.root / k).resolve()
        if self.root not in p.parents:
            raise PathTraversalError(f"key {key!r} resolves outside the store root")
        return p

    def _sidecar(self, key: str) -> Path:
        return self.root / META_DIR / (self._key(key) + ".sha256")

    def _copy_atomic(self, src: Path, dest: Path) -> None:
        """Temp file in the destination dir + os.replace: a failure leaves no partial final file."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=dest.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as out, open(src, "rb") as inp:
                while block := inp.read(1 << 20):
                    out.write(block)
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp, dest)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def _recorded_sha(self, key: str) -> str | None:
        sc = self._sidecar(key)
        return sc.read_text(encoding="utf-8").strip() if sc.is_file() else None

    # ---- interface
    def put_file(self, local_path: Path, key: str, sha256: str | None = None) -> TransferResult:
        dest = self._path(key)
        src = Path(local_path)
        actual = sha256_file(src)
        if sha256 is not None and sha256 != actual:
            raise ArtifactIntegrityError(
                f"{src} hashes to {actual[:12]}... but caller expected {sha256[:12]}...; the file changed "
                "since it was hashed. Refusing to upload."
            )
        if dest.is_file():
            existing = self._recorded_sha(key) or sha256_file(dest)
            if existing == actual:
                if self._recorded_sha(key) is None:
                    atomic_write_text(self._sidecar(key), actual + "\n")
                return TransferResult(
                    key,
                    ArtifactStatus.UPLOADED,
                    actual,
                    0,
                    skipped_identical=True,
                    detail="identical bytes already stored",
                )
            raise ArtifactOverwriteError(
                f"key {key!r} already holds different bytes (stored {existing[:12]}..., "
                f"new {actual[:12]}...); "
                "artifacts are immutable. Use a new key or remove the old object deliberately."
            )
        self._copy_atomic(src, dest)
        atomic_write_text(self._sidecar(key), actual + "\n")
        return TransferResult(key, ArtifactStatus.UPLOADED, actual, 1)

    def get_file(self, key: str, dest: Path) -> Path:
        src = self._path(key)
        if not src.is_file():
            raise NotFoundError(f"key {key!r} not found in local store {self.root}")
        dest = Path(dest)
        self._copy_atomic(src, dest)
        return dest

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def stat(self, key: str) -> StoredObject:
        p = self._path(key)
        if not p.is_file():
            raise NotFoundError(f"key {key!r} not found in local store {self.root}")
        return StoredObject(self._key(key), p.stat().st_size, self._recorded_sha(key))

    def list(self, prefix: str) -> list[StoredObject]:
        out: list[StoredObject] = []
        for p in sorted(self.root.rglob("*")):
            if not p.is_file() or p.suffix == ".tmp":
                continue
            rel = p.relative_to(self.root).as_posix()
            if rel.split("/", 1)[0] == META_DIR or not rel.startswith(prefix):
                continue
            out.append(StoredObject(rel, p.stat().st_size, self._recorded_sha(rel)))
        return out

    def verify(self, key: str, expected_sha256: str, scratch_dir: Path) -> TransferResult:
        """Re-read the stored bytes and recompute SHA-256 (the sidecar is not trusted)."""
        p = self._path(key)
        if not p.is_file():
            return TransferResult(key, ArtifactStatus.FAILED, None, 1, detail="key not found in store")
        actual = sha256_file(p)
        if actual == expected_sha256:
            return TransferResult(key, ArtifactStatus.VERIFIED, actual, 1)
        return TransferResult(
            key,
            ArtifactStatus.MISMATCH,
            actual,
            1,
            detail=f"recomputed {actual[:12]}... != expected {expected_sha256[:12]}...",
        )
