# ruff: noqa: E501, B023
"""Verifier-owned synthetic trial builder (independent copy; real TrialRecorder, real H.264)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from robotevalops.recording.writers import TrialRecorder
from robotevalops.schemas import (
    ArtifactRef,
    ArtifactRole,
    ArtifactStatus,
    ControllerType,
    Intervention,
    Provenance,
    RecordingQuality,
    TaskOutcome,
    TerminationReason,
    TrialManifestEntry,
    TrialState,
)
from robotevalops.util import sha256_file

STATE_NAMES = ["x", "y"]
ACTION_NAMES = ["dx", "dy"]


def make_trial(
    run_dir: Path,
    trial_id: str = "t1",
    *,
    n: int = 10,
    fps: float = 10.0,
    provenance: Provenance = Provenance.SIMULATION,
    video: bool = True,
    controller_type: ControllerType = ControllerType.SCRIPTED,
    outcome: TaskOutcome = TaskOutcome.SUCCESS,
    intervention: Intervention = Intervention.NONE,
    duration_s: float | None = None,
) -> TrialManifestEntry:
    """Record a synthetic trial under run_dir/trials/<id>/ and return its manifest entry with hashes."""
    tdir = run_dir / "trials" / trial_id
    rec = TrialRecorder(
        tdir, fps, STATE_NAMES, ACTION_NAMES, provenance, frame_size=(32, 24) if video else None
    )
    for i in range(n):
        img = np.full((24, 32, 3), (i * 20) % 255, dtype=np.uint8) if video else None
        rec.add(i / fps, img, [float(i), 0.5], [0.1, -0.1])
    rec.close(expected_steps=n)
    arts = []
    for role, name in ((ArtifactRole.TRACE, "trace.jsonl"), (ArtifactRole.VIDEO, "video.mp4")):
        p = tdir / name
        if p.is_file():
            arts.append(
                ArtifactRef(
                    role=role,
                    relpath=f"trials/{trial_id}/{name}",
                    sha256=sha256_file(p),
                    size_bytes=p.stat().st_size,
                    status=ArtifactStatus.PRESENT,
                )
            )
    return TrialManifestEntry(
        trial_id=trial_id,
        state=TrialState.COMPLETED,
        task_outcome=outcome,
        termination_reason=TerminationReason.SUCCESS_CRITERION_MET,
        recording_quality=RecordingQuality.UNCHECKED,
        intervention=intervention,
        condition_name="nominal",
        controller_id="scripted_a",
        controller_type=controller_type,
        controller_config_hash="abc",
        model_artifact_sha256=None,
        seed=1,
        duration_s=duration_s if duration_s is not None else n / fps,
        provenance=provenance,
        artifacts=arts,
    )


def rewrite_hash(run_dir: Path, entry: TrialManifestEntry) -> TrialManifestEntry:
    """Re-record sha256/size for entry artifacts (use after deliberately editing a fixture file)."""
    e = entry.model_copy(deep=True)
    for a in e.artifacts:
        p = run_dir / a.relpath
        if p.is_file():
            a.sha256 = sha256_file(p)
            a.size_bytes = p.stat().st_size
    return e
