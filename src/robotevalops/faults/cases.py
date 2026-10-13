"""Fault cases F01-F09. Each builds its OWN real bad fixture in a temp workdir (synthetic frames/states
produced by TrialRecorder, never real robot data), runs the REAL detector, and returns a FaultResult.

evidence_preserved: after detection (and quarantine where applicable) the offending source bytes are
still present and byte-identical (SHA-256) to what they were when the fault was injected.
misleading_success_prevented: the trial claimed success, yet QA failed/rejected it, an error was
raised, or the transfer was reported as failed - never a clean pass.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from robotevalops.errors import TransferTimeoutError
from robotevalops.qa.quarantine import quarantine_trial
from robotevalops.qa.trial_qa import qa_trial
from robotevalops.recording.manifest import build_manifest, read_manifest, validate_manifest, write_manifest
from robotevalops.recording.writers import TrialRecorder
from robotevalops.schemas import (
    ArtifactRef,
    ArtifactRole,
    ArtifactStatus,
    ControllerType,
    FaultResult,
    Intervention,
    Provenance,
    QACode,
    QAFlag,
    QAReport,
    RecordingQuality,
    Severity,
    TaskOutcome,
    TerminationReason,
    TrialManifestEntry,
    TrialState,
)
from robotevalops.storage.local import LocalArtifactStore
from robotevalops.storage.package import load_state, upload_run
from robotevalops.storage.retry import RetryPolicy, call_with_retry
from robotevalops.util import RUBRIC_VERSION, sha256_file, utcnow

CASE_IDS = (
    "F01_missing_video",
    "F02_truncated_video",
    "F03_nonmonotonic_timestamps",
    "F04_nonfinite_action",
    "F05_wrong_schema",
    "F06_missing_model_artifact",
    "F07_duplicate_trial_id",
    "F08_hash_mismatch",
    "F09_transfer_timeout",
    "F10_interrupted_runner",
)
FPS = 10.0
N_FRAMES = 12


# --------------------------------------------------------------------------- fixture builder


def build_trial(
    workdir: Path, trial_id: str = "fault_trial", *, learned: bool = False, video: bool = True
) -> tuple[Path, TrialManifestEntry]:
    """Record a small SYNTHETIC trial (generated gradient frames, scripted numbers) that claims SUCCESS."""
    run_dir = workdir / "runs" / "fault_session"
    tdir = run_dir / "trials" / trial_id
    if tdir.exists():
        shutil.rmtree(tdir)
    rec = TrialRecorder(
        tdir,
        FPS,
        ["x", "y"],
        ["dx", "dy"],
        Provenance.MOCK,
        frame_size=(32, 24) if video else None,
        video_kind="synthetic_generated_frames",
    )
    for i in range(N_FRAMES):
        img = np.full((24, 32, 3), (i * 20) % 255, dtype=np.uint8) if video else None
        rec.add(i / FPS, img, [float(i), 0.5], [0.1, -0.1])
    rec.close(expected_steps=N_FRAMES)
    arts: list[ArtifactRef] = []
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
    model_sha = None
    if learned:
        model_sha = "ab" * 32  # hash of a checkpoint that is deliberately never written to disk
        arts.append(ArtifactRef(role=ArtifactRole.MODEL, relpath="models/policy.pt", sha256=model_sha))
    entry = TrialManifestEntry(
        trial_id=trial_id,
        state=TrialState.COMPLETED,
        task_outcome=TaskOutcome.SUCCESS,
        termination_reason=TerminationReason.SUCCESS_CRITERION_MET,
        recording_quality=RecordingQuality.UNCHECKED,
        intervention=Intervention.NONE,
        condition_name="nominal",
        controller_id="fault_fixture",
        controller_type=ControllerType.LEARNED if learned else ControllerType.SCRIPTED,
        controller_config_hash="fixture",
        model_artifact_sha256=model_sha,
        seed=0,
        duration_s=N_FRAMES / FPS,
        provenance=Provenance.MOCK,
        artifacts=arts,
    )
    return run_dir, entry


def _rehash(run_dir: Path, entry: TrialManifestEntry, role: ArtifactRole) -> TrialManifestEntry:
    """Record the (already corrupted) file's hash so ONLY the intended detector fires."""
    e = entry.model_copy(deep=True)
    for a in e.artifacts:
        p = run_dir / a.relpath
        if a.role == role and p.is_file():
            a.sha256, a.size_bytes = sha256_file(p), p.stat().st_size
    return e


def _lines(p: Path) -> list[str]:
    return p.read_text(encoding="utf-8").splitlines()


def _result(
    case_id: str,
    description: str,
    expected: QACode,
    flags: list[QAFlag],
    *,
    evidence_preserved: bool,
    misleading_prevented: bool,
    details: dict[str, Any] | None = None,
) -> FaultResult:
    codes = [f.code.value for f in flags]
    msg = next((f.message for f in flags if f.code == expected), flags[0].message if flags else "")
    return FaultResult(
        case_id=case_id,
        description=description,
        expected_code=expected,
        detected=expected.value in codes,
        detected_codes=sorted(set(codes)),
        message=msg,
        evidence_preserved=evidence_preserved,
        misleading_success_prevented=misleading_prevented,
        executed_at=utcnow(),
        details=details or {},
    )


def _qa_and_quarantine(
    run_dir: Path, entry: TrialManifestEntry, **kw: Any
) -> tuple[QAReport, QAReport, dict[str, str]]:
    """Run QA, quarantine offending artifacts (copies), return (report, quarantined report, sha-before)."""
    before = {
        a.relpath: sha256_file(run_dir / a.relpath)
        for a in entry.artifacts
        if (run_dir / a.relpath).is_file()
    }
    rep = qa_trial(run_dir, entry, **kw)
    qrep, _ = quarantine_trial(run_dir, entry.trial_id, rep)
    return rep, qrep, before


def _unchanged(run_dir: Path, before: dict[str, str]) -> bool:
    return all((run_dir / r).is_file() and sha256_file(run_dir / r) == h for r, h in before.items())


def _standard(
    case_id: str,
    description: str,
    expected: QACode,
    run_dir: Path,
    entry: TrialManifestEntry,
    *,
    need_quarantine_copy: bool = False,
    **kw: Any,
) -> FaultResult:
    rep, qrep, before = _qa_and_quarantine(run_dir, entry, **kw)
    preserved = _unchanged(run_dir, before)
    for rel in qrep.quarantined:  # the quarantine copy must be byte-identical to the preserved source
        cp = run_dir / "quarantine" / entry.trial_id / rel
        preserved = preserved and cp.is_file() and sha256_file(cp) == before.get(rel)
    if need_quarantine_copy:
        preserved = preserved and bool(qrep.quarantined)
    prevented = (
        entry.task_outcome == TaskOutcome.SUCCESS
        and rep.quality == RecordingQuality.FAIL
        and not rep.accepted
    )
    return _result(
        case_id,
        description,
        expected,
        rep.flags,
        evidence_preserved=preserved,
        misleading_prevented=prevented,
        details={
            "quality": rep.quality.value,
            "accepted": rep.accepted,
            "rejection_reasons": rep.rejection_reasons,
            "quarantined": qrep.quarantined,
            "claimed_outcome": entry.task_outcome.value,
        },
    )


# --------------------------------------------------------------------------- cases


def f01_missing_video(workdir: Path) -> FaultResult:
    run_dir, entry = build_trial(workdir)
    (run_dir / entry.artifacts[1].relpath).unlink()  # video.mp4 removed
    return _standard(
        "F01_missing_video",
        "trial lists video.mp4 but the file is gone",
        QACode.MISSING_VIDEO,
        run_dir,
        entry,
    )


def f02_truncated_video(workdir: Path) -> FaultResult:
    run_dir, entry = build_trial(workdir)
    p = run_dir / entry.artifacts[1].relpath
    data = p.read_bytes()
    p.write_bytes(data[: len(data) // 2])  # really truncate the H.264 mp4 bytes
    entry = _rehash(run_dir, entry, ArtifactRole.VIDEO)
    res = _standard(
        "F02_truncated_video",
        "H.264 mp4 cut to half its bytes (hash re-recorded)",
        QACode.TRUNCATED_VIDEO,
        run_dir,
        entry,
        need_quarantine_copy=True,
    )
    res.details.update(original_bytes=len(data), truncated_bytes=len(data) // 2)
    return res


def f03_nonmonotonic_timestamps(workdir: Path) -> FaultResult:
    run_dir, entry = build_trial(workdir)
    p = run_dir / entry.artifacts[0].relpath
    lines = _lines(p)
    row = json.loads(lines[6])
    row["t"] = 0.05  # row index 5 (t=0.5 before it) now goes backwards
    lines[6] = json.dumps(row)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    entry = _rehash(run_dir, entry, ArtifactRole.TRACE)
    return _standard(
        "F03_nonmonotonic_timestamps",
        "one trace timestamp goes backwards",
        QACode.NONMONOTONIC_TIMESTAMPS,
        run_dir,
        entry,
        need_quarantine_copy=True,
    )


def f04_nonfinite_action(workdir: Path) -> FaultResult:
    run_dir, entry = build_trial(workdir)
    p = run_dir / entry.artifacts[0].relpath
    lines = _lines(p)
    lines[4] = (
        '{"i": 3, "t": 0.3, "state": [3.0, 0.5], "action": [NaN, -0.1]}'  # literal NaN, as Python emits
    )
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    entry = _rehash(run_dir, entry, ArtifactRole.TRACE)
    return _standard(
        "F04_nonfinite_action",
        "an action value is a literal NaN",
        QACode.NONFINITE_VALUE,
        run_dir,
        entry,
        need_quarantine_copy=True,
    )


def f05_wrong_schema(workdir: Path) -> FaultResult:
    run_dir, entry = build_trial(workdir)
    p = run_dir / entry.artifacts[0].relpath
    lines = _lines(p)
    h = json.loads(lines[0])
    h["schema_version"] = "0.0-legacy"
    lines[0] = json.dumps(h)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    entry = _rehash(run_dir, entry, ArtifactRole.TRACE)
    return _standard(
        "F05_wrong_schema",
        "trace header declares an unsupported schema_version",
        QACode.SCHEMA_MISMATCH,
        run_dir,
        entry,
        need_quarantine_copy=True,
    )


def f06_missing_model_artifact(workdir: Path) -> FaultResult:
    run_dir, entry = build_trial(workdir, learned=True)
    return _standard(
        "F06_missing_model_artifact",
        "learned-controller trial references models/policy.pt which does not exist",
        QACode.MISSING_MODEL_ARTIFACT,
        run_dir,
        entry,
    )


def f07_duplicate_trial_id(workdir: Path) -> FaultResult:
    run_dir, entry = build_trial(workdir)
    m = build_manifest(
        session_id="fault_session",
        provenance=Provenance.MOCK,
        backend="mock",
        task_id="fixture",
        rubric_version=RUBRIC_VERSION,
        trials=[entry, entry],
    )
    path = run_dir / "manifest.json"
    write_manifest(path, m)
    before = sha256_file(path)
    flags = validate_manifest(read_manifest(path))
    preserved = (
        sha256_file(path) == before and len(read_manifest(path).trials) == 2
    )  # nothing deduped/dropped
    return _result(
        "F07_duplicate_trial_id",
        "manifest lists the same trial_id twice",
        QACode.DUPLICATE_ID,
        flags,
        evidence_preserved=preserved,
        misleading_prevented=any(f.severity.value == "error" for f in flags),
        details={"manifest_trials": 2, "claimed_outcome": entry.task_outcome.value},
    )


def f08_hash_mismatch(workdir: Path) -> FaultResult:
    run_dir, entry = build_trial(workdir)  # hashes recorded here...
    p = run_dir / entry.artifacts[0].relpath
    b = bytearray(p.read_bytes())
    idx = max(i for i, c in enumerate(b) if 0x30 <= c <= 0x39)
    b[idx] ^= (
        0x01  # ...then one digit byte is flipped after hashing (stays valid JSON, so ONLY the hash fails)
    )
    p.write_bytes(bytes(b))
    return _standard(
        "F08_hash_mismatch",
        "one byte of trace.jsonl flipped after its hash was recorded",
        QACode.HASH_MISMATCH,
        run_dir,
        entry,
        need_quarantine_copy=True,
    )


class _AlwaysTimeoutStore(LocalArtifactStore):
    """Injected store: after `ok_first` successful puts every transfer times out; retries are real
    (call_with_retry with a fake sleep) and counted."""

    def __init__(self, root: Path, ok_first: int = 1, max_attempts: int = 3) -> None:
        super().__init__(root)
        self.ok_first, self.max_attempts = ok_first, max_attempts
        self.puts_ok = 0
        self.timeout_calls = 0
        self.sleeps: list[float] = []

    def put_file(self, local_path: Path, key: str, sha256: str | None = None):
        if self.puts_ok < self.ok_first:
            self.puts_ok += 1
            return super().put_file(local_path, key, sha256)

        def attempt() -> None:
            self.timeout_calls += 1
            raise TimeoutError("injected: connection timed out")

        call_with_retry(
            attempt,
            policy=RetryPolicy(max_attempts=self.max_attempts, base_delay_s=1.0),
            sleep=self.sleeps.append,
            what=f"upload {key}",
        )
        raise AssertionError("unreachable")  # pragma: no cover


def f09_transfer_timeout(workdir: Path) -> FaultResult:
    run_dir, entry = build_trial(workdir)
    (run_dir / "manifest.json").write_text('{"fixture": true}\n', encoding="utf-8")
    before = {p.relative_to(run_dir).as_posix(): sha256_file(p) for p in run_dir.rglob("*") if p.is_file()}
    store = _AlwaysTimeoutStore(workdir / "store_timeout", ok_first=1, max_attempts=3)
    raised: TransferTimeoutError | None = None
    try:  # direct call: the contract says TransferTimeoutError after bounded retries
        store.puts_ok = store.ok_first
        store.put_file(run_dir / "manifest.json", "runs/fault_session/manifest.json")
    except TransferTimeoutError as exc:
        raised = exc
    direct_calls, direct_attempts = store.timeout_calls, getattr(raised, "attempts", None)
    store.puts_ok, store.timeout_calls = 0, 0
    rep = upload_run(store, run_dir, "fault_session")  # one object goes through, the rest time out
    state = load_state(run_dir)
    statuses = {r: v["status"] for r, v in state.items()}
    uploaded_ok = [a for a in rep.artifacts if a.status == "uploaded"]
    partial_preserved = (
        len(uploaded_ok) == 1
        and statuses.get(uploaded_ok[0].relpath) == "uploaded"
        and all(s == "failed" for r, s in statuses.items() if r != uploaded_ok[0].relpath)
        and all(store.exists("runs/fault_session/" + a.relpath) for a in uploaded_ok)
    )
    after = {
        p.relative_to(run_dir).as_posix(): sha256_file(p)
        for p in run_dir.rglob("*")
        if p.is_file() and ".transfer" not in p.parts
    }
    sources_unchanged = all(after.get(r) == h for r, h in before.items() if not r.startswith(".transfer"))
    bounded = (
        raised is not None
        and direct_calls == 3
        and direct_attempts == 3
        and store.timeout_calls == 3 * (len(rep.artifacts) - 1)
    )
    flags: list[QAFlag] = []
    if raised is not None:
        flags.append(
            QAFlag(
                code=QACode.TRANSFER_TIMEOUT,
                severity=Severity.ERROR,
                message=str(raised),
                subject="runs/fault_session/manifest.json",
                evidence={"attempts": direct_attempts},
            )
        )
    res = _result(
        "F09_transfer_timeout",
        "object store times out on every transfer after the first",
        QACode.TRANSFER_TIMEOUT,
        flags,
        evidence_preserved=sources_unchanged and partial_preserved,
        misleading_prevented=bounded and not rep.ok and rep.checksum_agreement != 1.0,
        details={
            "max_attempts": 3,
            "direct_attempts": direct_attempts,
            "bounded_retries": bounded,
            "report_ok": rep.ok,
            "state_statuses": statuses,
            "sleeps": store.sleeps[:2],
            "checksum_agreement": rep.checksum_agreement,
        },
    )
    return res


CASES: dict[str, Callable[[Path], FaultResult]] = {
    "F01_missing_video": f01_missing_video,
    "F02_truncated_video": f02_truncated_video,
    "F03_nonmonotonic_timestamps": f03_nonmonotonic_timestamps,
    "F04_nonfinite_action": f04_nonfinite_action,
    "F05_wrong_schema": f05_wrong_schema,
    "F06_missing_model_artifact": f06_missing_model_artifact,
    "F07_duplicate_trial_id": f07_duplicate_trial_id,
    "F08_hash_mismatch": f08_hash_mismatch,
    "F09_transfer_timeout": f09_transfer_timeout,
}
