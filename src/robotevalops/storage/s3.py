"""S3ArtifactStore: optional boto3 backend for a USER-OWNED bucket.

Safety rules (enforced by construction):
  * credentials come ONLY from boto3's normal chain (env, shared config, role); this class accepts no keys;
  * it never creates buckets, changes bucket policy, or touches IAM - only head/get/put/list on objects;
  * the content hash is a SHA-256 stored as object metadata ('sha256'). The S3 ETag is NEVER used as a
    content hash (multipart/KMS ETags are not MD5/SHA of the content).
Known limitation: head-then-put idempotency is not an atomic conditional write; two concurrent writers
to the same new key could race. Run one uploader per session.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from robotevalops.errors import (
    ArtifactIntegrityError,
    ArtifactOverwriteError,
    CapabilityUnavailableError,
    NotFoundError,
    RobotEvalOpsError,
)
from robotevalops.schemas import ArtifactStatus
from robotevalops.storage.base import ArtifactStore, StoredObject, TransferResult
from robotevalops.storage.local import strict_key
from robotevalops.storage.retry import RetryPolicy, call_with_retry
from robotevalops.util import sha256_file

_RETRYABLE_CODES = {
    "RequestTimeout",
    "RequestTimeTooSkewed",
    "SlowDown",
    "Throttling",
    "ThrottlingException",
    "InternalError",
    "ServiceUnavailable",
    "RequestLimitExceeded",
}


def _client_error_code(exc: BaseException) -> tuple[str, int]:
    resp = getattr(exc, "response", None)
    if not isinstance(resp, dict):
        return "", 0
    err = resp.get("Error", {})
    return str(err.get("Code", "")), int(resp.get("ResponseMetadata", {}).get("HTTPStatusCode", 0) or 0)


def is_retryable_s3_error(exc: BaseException) -> bool:
    """Network/timeouts and 5xx/throttling are retried; 4xx (auth, not found) are not."""
    name = type(exc).__name__
    if name in {
        "EndpointConnectionError",
        "ConnectTimeoutError",
        "ReadTimeoutError",
        "ConnectionClosedError",
        "ResponseStreamingError",
        "IncompleteReadError",
    }:
        return True
    code, status = _client_error_code(exc)
    return code in _RETRYABLE_CODES or status >= 500 or isinstance(exc, TimeoutError | ConnectionError)


def _is_not_found(exc: BaseException) -> bool:
    code, status = _client_error_code(exc)
    return code in {"404", "NoSuchKey", "NotFound"} or status == 404


class S3ArtifactStore(ArtifactStore):
    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        client: Any | None = None,
        *,
        retry: RetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        region_name: str | None = None,
    ) -> None:
        if not bucket:
            raise ValueError("bucket name is required (an existing, user-owned bucket)")
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.retry = retry or RetryPolicy()
        self._sleep = sleep
        self._clock = clock
        self.client = client if client is not None else self._make_client(region_name)

    @staticmethod
    def _make_client(region_name: str | None) -> Any:
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:
            raise CapabilityUnavailableError(
                "S3 storage needs boto3 (not installed). Install the optional extra: "
                "`uv sync --extra s3` or `pip install boto3`. The local store works without it."
            ) from exc
        cfg = Config(connect_timeout=10, read_timeout=60, retries={"max_attempts": 1})
        # Normal credential chain only: no access keys are ever passed here.
        return boto3.client("s3", region_name=region_name, config=cfg)

    # ---- helpers
    def _full(self, key: str) -> str:
        k = strict_key(key)
        return f"{self.prefix}/{k}" if self.prefix else k

    def _logical(self, full: str) -> str:
        return full[len(self.prefix) + 1 :] if self.prefix else full

    def _retry(self, fn: Callable[[], Any], what: str) -> tuple[Any, int]:
        return call_with_retry(
            fn,
            policy=self.retry,
            sleep=self._sleep,
            clock=self._clock,
            is_retryable=is_retryable_s3_error,
            what=what,
        )

    def _head(self, key: str) -> tuple[dict[str, Any] | None, int]:
        full = self._full(key)

        def go() -> dict[str, Any] | None:
            try:
                return self.client.head_object(Bucket=self.bucket, Key=full)
            except Exception as exc:
                if _is_not_found(exc):
                    return None
                raise

        res, attempts = self._retry(go, f"head s3://{self.bucket}/{full}")
        return res, attempts

    def _download_hash(self, key: str, scratch_dir: Path | None = None) -> tuple[str, int]:
        full = self._full(key)
        sd = Path(scratch_dir) if scratch_dir else Path(tempfile.gettempdir())
        sd.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=sd, prefix="roe-verify-", suffix=".tmp")
        os.close(fd)
        try:
            _, attempts = self._retry(
                lambda: self.client.download_file(self.bucket, full, tmp),
                f"download s3://{self.bucket}/{full}",
            )
            return sha256_file(tmp), attempts
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp)

    # ---- interface
    def put_file(self, local_path: Path, key: str, sha256: str | None = None) -> TransferResult:
        src = Path(local_path)
        actual = sha256_file(src)
        if sha256 is not None and sha256 != actual:
            raise ArtifactIntegrityError(
                f"{src} hashes to {actual[:12]}... but caller expected {sha256[:12]}...; refusing to upload."
            )
        size = src.stat().st_size
        full = self._full(key)
        head, attempts = self._head(key)
        if head is not None:
            meta = {k.lower(): v for k, v in (head.get("Metadata") or {}).items()}
            claimed = meta.get("sha256")
            if int(head.get("ContentLength", -1)) != size:
                remote_sha = claimed or "(different size)"
            else:  # same size: decide from the real bytes, never from metadata
                remote_sha, a2 = self._download_hash(key)
                attempts += a2
                if remote_sha == actual:
                    return TransferResult(
                        key,
                        ArtifactStatus.UPLOADED,
                        actual,
                        attempts,
                        skipped_identical=True,
                        detail="identical bytes already stored (re-hashed from the object)",
                    )
                if claimed == actual:
                    return TransferResult(
                        key,
                        ArtifactStatus.MISMATCH,
                        remote_sha,
                        attempts,
                        detail=f"s3://{self.bucket}/{full} is CORRUPTED: metadata claims "
                        f"{actual[:12]}... but "
                        f"the object bytes hash to {remote_sha[:12]}.... Not skipped, not overwritten; "
                        "inspect and remove deliberately.",
                    )
            raise ArtifactOverwriteError(
                f"s3://{self.bucket}/{full} already holds different bytes (stored sha256 "
                f"{str(remote_sha)[:12]}..., new {actual[:12]}...); artifacts are immutable. Use a new key."
            )
        try:
            _, a3 = self._retry(
                lambda: self.client.upload_file(
                    str(src), self.bucket, full, ExtraArgs={"Metadata": {"sha256": actual}}
                ),
                f"upload s3://{self.bucket}/{full}",
            )
        except RobotEvalOpsError:
            raise
        except Exception as exc:
            raise RobotEvalOpsError(f"S3 upload of {key!r} failed (non-retryable): {exc}") from exc
        return TransferResult(key, ArtifactStatus.UPLOADED, actual, attempts + a3)

    def get_file(self, key: str, dest: Path) -> Path:
        full = self._full(key)
        head, _ = self._head(key)
        if head is None:
            raise NotFoundError(f"s3://{self.bucket}/{full} not found")
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=dest.name + ".", suffix=".tmp")
        os.close(fd)
        try:
            self._retry(lambda: self.client.download_file(self.bucket, full, tmp), f"download {full}")
            os.replace(tmp, dest)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        return dest

    def exists(self, key: str) -> bool:
        return self._head(key)[0] is not None

    def stat(self, key: str) -> StoredObject:
        head, _ = self._head(key)
        if head is None:
            raise NotFoundError(f"s3://{self.bucket}/{self._full(key)} not found")
        meta = {k.lower(): v for k, v in (head.get("Metadata") or {}).items()}
        return StoredObject(strict_key(key), int(head["ContentLength"]), meta.get("sha256"))

    def list(self, prefix: str) -> list[StoredObject]:
        full_prefix = f"{self.prefix}/{prefix}" if self.prefix else prefix
        out: list[StoredObject] = []
        token: str | None = None
        while True:
            kw: dict[str, Any] = {"Bucket": self.bucket, "Prefix": full_prefix}
            if token:
                kw["ContinuationToken"] = token

            def list_page(kw: dict[str, Any] = kw) -> Any:
                return self.client.list_objects_v2(**kw)

            resp, _ = self._retry(list_page, "list objects")
            for obj in resp.get("Contents", []):
                logical = self._logical(obj["Key"])
                head, _ = self._head(logical)
                meta = {k.lower(): v for k, v in ((head or {}).get("Metadata") or {}).items()}
                out.append(StoredObject(logical, int(obj["Size"]), meta.get("sha256")))
            if not resp.get("IsTruncated"):
                return out
            token = resp.get("NextContinuationToken")

    def verify(self, key: str, expected_sha256: str, scratch_dir: Path) -> TransferResult:
        """Download the object and recompute SHA-256 over the bytes. The ETag is never consulted: for
        multipart or SSE-KMS uploads it is not the content hash. Missing object -> FAILED."""
        head, attempts = self._head(key)
        if head is None:
            return TransferResult(key, ArtifactStatus.FAILED, None, attempts, detail="object not found")
        actual, a2 = self._download_hash(key, scratch_dir)
        total = attempts + a2
        if actual == expected_sha256:
            return TransferResult(key, ArtifactStatus.VERIFIED, actual, total)
        return TransferResult(
            key,
            ArtifactStatus.MISMATCH,
            actual,
            total,
            detail=f"recomputed {actual[:12]}... != expected {expected_sha256[:12]}...",
        )
