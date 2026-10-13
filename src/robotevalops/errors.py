"""Shared exception hierarchy. Every error carries an actionable message."""

from __future__ import annotations


class RobotEvalOpsError(Exception):
    """Base class for all expected, user-actionable errors."""


class InvalidTransitionError(RobotEvalOpsError):
    """A lifecycle state transition that is not in the documented allowed set."""


class DuplicateIdError(RobotEvalOpsError):
    """An identifier (session/trial/artifact) that must be unique already exists."""


class NotFoundError(RobotEvalOpsError):
    """A referenced session/trial/artifact does not exist."""


class DeviceBusyError(RobotEvalOpsError):
    """Another runner already holds the lock for this physical device."""


class ScoreProtectionError(RobotEvalOpsError):
    """An attempt to overwrite an existing score/result without an audited edit."""


class CapabilityUnavailableError(RobotEvalOpsError):
    """An optional dependency or hardware capability is not installed/connected."""


class HardwareRefusedError(RobotEvalOpsError):
    """Hardware motion refused: missing explicit mode, acknowledgement, or preflight."""


class PreflightFailedError(RobotEvalOpsError):
    """A preflight check failed; the message lists each failed check."""


class ArtifactIntegrityError(RobotEvalOpsError):
    """Checksum mismatch or missing bytes for an artifact."""


class ArtifactOverwriteError(RobotEvalOpsError):
    """An upload would replace different bytes at an existing key."""


class TransferTimeoutError(RobotEvalOpsError):
    """A storage transfer exceeded its timeout after bounded retries."""


class PathTraversalError(RobotEvalOpsError):
    """A path escapes its root or targets a forbidden (credential/unrelated) file."""


class SchemaMismatchError(RobotEvalOpsError):
    """A manifest/trace/config does not match the expected schema version."""
