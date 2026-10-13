# ruff: noqa: E501, B023
"""V5: storage and QA attacks on real files (local store; S3 is covered separately by moto in tests/data)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from robotevalops.cli.main import app
from robotevalops.core.service import EvalService
from robotevalops.errors import (
    ArtifactOverwriteError,
    PathTraversalError,
    TransferTimeoutError,
)
from robotevalops.qa.quarantine import quarantine_trial
from robotevalops.qa.trial_qa import qa_trial
from robotevalops.schemas import (
    ArtifactStatus,
    QACode,
    RecordingQuality,
    TrialManifestEntry,
)
from robotevalops.storage.local import LocalArtifactStore
from robotevalops.storage.package import build_package, collect_run_files, upload_run, verify_run
from robotevalops.storage.retry import RetryPolicy, call_with_retry
from robotevalops.util import sha256_file

from .qa_helpers import make_trial

cli = CliRunner()


# ------------------------------------------------------------------------------------ path handling
@pytest.mark.parametrize(
    "key",
    [
        "../x",
        "/abs/x",
        "a/../../x",
        "a//b",
        "a/./b",
        "C:\\x",
        "C:/x",
        "a\\b",
        ".meta/x",
        "",
        "a/",
        "..",
        "runs/s/../../../x",
        "a\x00b",
        "runs/s/../../.meta/k.sha256",
    ],
)
def test_store_rejects_hostile_keys(tmp_path: Path, key: str) -> None:
    store = LocalArtifactStore(tmp_path / "store")
    src = tmp_path / "f.bin"
    src.write_bytes(b"x")
    with pytest.raises(PathTraversalError):
        store.put_file(src, key)
    assert not (tmp_path / "x").exists()
    assert [p for p in (tmp_path / "store").rglob("*") if p.is_file()] == []


@pytest.mark.skipif(os.name != "nt", reason="junctions are a Windows feature")
def test_junction_escape_from_store_and_run_dir(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("TOP SECRET", encoding="utf-8")
    store_root = tmp_path / "store"
    store = LocalArtifactStore(store_root)
    link = store_root / "runs" / "s1" / "link"
    link.parent.mkdir(parents=True)
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
    src = tmp_path / "f.bin"
    src.write_bytes(b"payload")
    with pytest.raises(PathTraversalError):
        store.put_file(src, "runs/s1/link/new.bin")
    assert not (outside / "new.bin").exists()
    # reading through the junction is refused too
    with pytest.raises(PathTraversalError):
        store.get_file("runs/s1/link/secret.txt", tmp_path / "leak.txt")
    assert not (tmp_path / "leak.txt").exists()
    # packaging a run dir that contains a junction must not collect the outside file
    run = tmp_path / "run"
    (run / "trials").mkdir(parents=True)
    (run / "trials" / "ok.txt").write_text("ok", encoding="utf-8")
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(run / "trials" / "jn"), str(outside)],
        check=True,
        capture_output=True,
    )
    files, blocked = collect_run_files(run)
    assert files == ["trials/ok.txt"], (files, blocked)
    rep = upload_run(store, run, "s2")
    assert all("secret" not in a.relpath for a in rep.artifacts)
    assert not list((store_root / "runs" / "s2").rglob("secret.txt"))
    assert sorted(x.name for x in outside.iterdir()) == ["secret.txt"]  # nothing written into the target


@pytest.mark.parametrize(
    "name",
    [
        ".env",
        ".aws/credentials",
        ".ssh/id_rsa",
        "id_ed25519",
        "x.pem",
        "x.key",
        "x.p12",
        ".netrc",
        ".git/config",
        "ENV/.ENV",
        "Credentials",
    ],
)
def test_credential_files_are_never_packaged(tmp_path: Path, name: str) -> None:
    run = tmp_path / "run"
    p = run / "trials" / "t" / name
    p.parent.mkdir(parents=True)
    p.write_text("AKIA...secret", encoding="utf-8")
    (run / "trials" / "t" / "trace.jsonl").write_text("{}", encoding="utf-8")
    rep = build_package(run, "s")
    assert [a.relpath for a in rep.artifacts] == ["trials/t/trace.jsonl"]
    assert (
        any(
            name.lower().split("/")[-1] in b["relpath"].lower()
            or ".aws" in b["relpath"].lower()
            or ".ssh" in b["relpath"].lower()
            or ".git" in b["relpath"].lower()
            for b in rep.blocked
        )
        or name == "ENV/.ENV"
    )


def test_common_secret_file_names_are_also_blocked(tmp_path: Path) -> None:
    run = tmp_path / "run"
    names = [
        "credentials.json",
        ".env.local",
        "prod.env",
        ".git-credentials",
        "id_ecdsa",
        "secrets.yaml",
        ".npmrc",
        "service-account.json",
        "token.txt",
    ]
    for n in names:
        (run / "trials" / "t").mkdir(parents=True, exist_ok=True)
        (run / "trials" / "t" / n).write_text("secret", encoding="utf-8")
    rep = build_package(run, "s")
    assert rep.artifacts == [], [a.relpath for a in rep.artifacts]


def test_overwrite_of_different_bytes_refused_original_intact(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "store")
    a = tmp_path / "a.bin"
    a.write_bytes(b"AAAA")
    r1 = store.put_file(a, "runs/s/a.bin")
    assert r1.status == ArtifactStatus.UPLOADED and r1.attempts == 1
    b = tmp_path / "b.bin"
    b.write_bytes(b"BBBB")
    with pytest.raises(ArtifactOverwriteError):
        store.put_file(b, "runs/s/a.bin")
    assert (tmp_path / "store" / "runs" / "s" / "a.bin").read_bytes() == b"AAAA"
    r3 = store.put_file(a, "runs/s/a.bin")  # identical re-upload is idempotent
    assert r3.skipped_identical and r3.attempts == 0


def test_caller_hash_that_does_not_match_file_is_refused(tmp_path: Path) -> None:
    from robotevalops.errors import ArtifactIntegrityError

    store = LocalArtifactStore(tmp_path / "store")
    a = tmp_path / "a.bin"
    a.write_bytes(b"AAAA")
    with pytest.raises(ArtifactIntegrityError):
        store.put_file(a, "runs/s/a.bin", sha256="0" * 64)
    assert not store.exists("runs/s/a.bin")


def test_partial_write_leaves_no_final_file_no_sidecar_no_tmp(tmp_path: Path, monkeypatch) -> None:
    import robotevalops.storage.local as loc

    store = LocalArtifactStore(tmp_path / "store")
    a = tmp_path / "a.bin"
    a.write_bytes(b"x" * 3_000_000)

    def boom(fd: int) -> None:
        raise OSError("disk full (injected)")

    monkeypatch.setattr(loc.os, "fsync", boom)
    with pytest.raises(OSError):
        store.put_file(a, "runs/s/a.bin")
    monkeypatch.undo()
    leftovers = [p.name for p in (tmp_path / "store").rglob("*") if p.is_file()]
    assert leftovers == [], leftovers
    assert not store.exists("runs/s/a.bin")


def test_verify_rereads_bytes_not_sidecar_or_size(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "store")
    a = tmp_path / "a.bin"
    a.write_bytes(b"A" * 1000)
    digest = sha256_file(a)
    store.put_file(a, "runs/s/a.bin")
    assert store.verify("runs/s/a.bin", digest, tmp_path).status == ArtifactStatus.VERIFIED
    stored = tmp_path / "store" / "runs" / "s" / "a.bin"
    stored.write_bytes(b"B" * 1000)  # same size, sidecar still claims the old hash
    assert store.stat("runs/s/a.bin").sha256 == digest  # the sidecar lies ...
    assert (
        store.verify("runs/s/a.bin", digest, tmp_path).status == ArtifactStatus.MISMATCH
    )  # ... verify does not


def test_reupload_does_not_trust_sidecar_over_stored_bytes(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "store")
    a = tmp_path / "a.bin"
    a.write_bytes(b"A" * 1000)
    store.put_file(a, "runs/s/a.bin")
    (tmp_path / "store" / "runs" / "s" / "a.bin").write_bytes(b"CORRUPT")
    res = store.put_file(a, "runs/s/a.bin")
    assert not res.skipped_identical, "corrupted stored object was reported as identical"


def test_resume_state_does_not_hide_object_missing_from_store(tmp_path: Path) -> None:
    """VF-11 (fixed): a lost object is re-uploaded, never reported as 'skipped: already uploaded'."""
    run = tmp_path / "run"
    run.mkdir()
    (run / "a.txt").write_text("hello", encoding="utf-8")
    store = LocalArtifactStore(tmp_path / "store")
    assert upload_run(store, run, "s").ok
    shutil.rmtree(tmp_path / "store" / "runs")  # object lost on the store side
    rep = upload_run(store, run, "s")
    assert store.exists("runs/s/a.txt")  # restored, not silently skipped
    assert rep.ok
    assert all("resume state" not in a.detail for a in rep.artifacts), rep.to_dict()["artifacts"]


def test_verify_run_detects_tampered_store_and_reports_agreement(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    for n in ("a.txt", "b.txt"):
        (run / n).write_text(n * 100, encoding="utf-8")
    store = LocalArtifactStore(tmp_path / "store")
    assert upload_run(store, run, "s").ok
    v = verify_run(store, run, "s")
    assert v.ok and v.checksum_agreement == 1.0
    (tmp_path / "store" / "runs" / "s" / "b.txt").write_text("b.txt" * 100 + "!", encoding="utf-8")
    v = verify_run(store, run, "s")
    assert not v.ok and v.count(ArtifactStatus.MISMATCH) == 1 and v.checksum_agreement == pytest.approx(0.5)
    (tmp_path / "store" / "runs" / "s" / "a.txt").unlink()
    v = verify_run(store, run, "s")
    assert v.count(ArtifactStatus.FAILED) == 1 and not v.ok


def test_retry_is_bounded_and_backoff_capped() -> None:
    sleeps: list[float] = []
    calls = {"n": 0}

    def always_fail() -> None:
        calls["n"] += 1
        raise TimeoutError("net")

    pol = RetryPolicy(max_attempts=5, base_delay_s=1.0, factor=2.0, max_delay_s=3.0)
    with pytest.raises(TransferTimeoutError) as ei:
        call_with_retry(always_fail, policy=pol, sleep=sleeps.append)
    assert calls["n"] == 5 and ei.value.attempts == 5  # type: ignore[attr-defined]
    assert sleeps == [1.0, 2.0, 3.0, 3.0]
    # non-retryable error propagates immediately, no sleep
    sleeps.clear()
    with pytest.raises(ValueError):
        call_with_retry(lambda: (_ for _ in ()).throw(ValueError("bad")), policy=pol, sleep=sleeps.append)
    assert sleeps == []
    # total timeout bounds the loop
    t = {"now": 0.0}
    with pytest.raises(TransferTimeoutError):
        call_with_retry(
            always_fail,
            policy=RetryPolicy(max_attempts=50, base_delay_s=10, max_delay_s=10, total_timeout_s=25),
            sleep=lambda d: t.__setitem__("now", t["now"] + d),
            clock=lambda: t["now"],
        )
    assert t["now"] <= 25
    # a call that "succeeds" later than the per-call timeout is a timeout, never a silent success
    clk = {"now": 0.0}

    def slow() -> str:
        clk["now"] += 100
        return "late"

    with pytest.raises(TransferTimeoutError):
        call_with_retry(
            slow,
            policy=RetryPolicy(max_attempts=2, per_call_timeout_s=5),
            sleep=lambda d: None,
            clock=lambda: clk["now"],
        )


# ------------------------------------------------------------------------------------ QA on real files
def _entry(tmp_path: Path, n: int = 12, **kw: Any) -> TrialManifestEntry:
    return make_trial(tmp_path, "t1", n=n, **kw)


def test_baseline_good_trial_has_no_error_flags(tmp_path: Path) -> None:
    rep = qa_trial(tmp_path, _entry(tmp_path))
    assert rep.quality in (RecordingQuality.PASS, RecordingQuality.FLAGGED)
    assert not [f for f in rep.flags if f.severity.value == "error"], rep.flags


def _codes(rep: Any) -> set[str]:
    return {f.code.value for f in rep.flags if f.severity.value == "error"}


@pytest.mark.parametrize("frac", [0.0, 0.01, 0.25, 0.5, 0.9, 0.96])
def test_truncated_h264_at_many_offsets_always_fails_qa(tmp_path: Path, frac: float) -> None:
    e = _entry(tmp_path, n=40)
    v = tmp_path / "trials" / "t1" / "video.mp4"
    data = v.read_bytes()
    v.write_bytes(data[: int(len(data) * frac)])
    # recorded hash deliberately NOT refreshed (so hash_mismatch also fires); then re-hash to isolate decode checks
    for a in e.artifacts:
        p = tmp_path / a.relpath
        a.sha256, a.size_bytes = sha256_file(p), p.stat().st_size
    rep = qa_trial(tmp_path, e)
    assert rep.quality == RecordingQuality.FAIL
    assert _codes(rep) & {"truncated_video", "undecodable_frames"}, _codes(rep)


def test_truncated_by_one_byte_and_garbage_with_moov_word(tmp_path: Path) -> None:
    e = _entry(tmp_path, n=40)
    v = tmp_path / "trials" / "t1" / "video.mp4"
    good = v.read_bytes()
    v.write_bytes(good[:-1])
    for a in e.artifacts:
        p = tmp_path / a.relpath
        a.sha256, a.size_bytes = sha256_file(p), p.stat().st_size
    from robotevalops.qa.checks import probe_video

    # losing the last container byte (trailing moov metadata) still decodes every frame: QA may pass it only
    # if ALL 40 frames really decode; any frame loss must be FAIL
    pr = probe_video(v)
    assert (qa_trial(tmp_path, e).quality == RecordingQuality.FAIL) or pr.decoded_frames == 40
    v.write_bytes(good[:-100])  # 100 bytes lost: moov is cut -> must fail
    for a in e.artifacts:
        p = tmp_path / a.relpath
        a.sha256, a.size_bytes = sha256_file(p), p.stat().st_size
    assert qa_trial(tmp_path, e).quality == RecordingQuality.FAIL
    v.write_bytes(b"moov" + os.urandom(5000))  # garbage that merely contains the word moov
    for a in e.artifacts:
        p = tmp_path / a.relpath
        a.sha256, a.size_bytes = sha256_file(p), p.stat().st_size
    rep = qa_trial(tmp_path, e)
    assert rep.quality == RecordingQuality.FAIL and "undecodable_frames" in _codes(rep)


def test_video_with_fewer_frames_than_trace_rows_fails(tmp_path: Path) -> None:
    e = _entry(tmp_path, n=20)
    short = make_trial(tmp_path / "other", "t1", n=10)  # valid 10-frame video
    shutil.copyfile(tmp_path / "other" / short.artifacts[1].relpath, tmp_path / "trials" / "t1" / "video.mp4")
    for a in e.artifacts:
        p = tmp_path / a.relpath
        a.sha256, a.size_bytes = sha256_file(p), p.stat().st_size
    rep = qa_trial(tmp_path, e)
    assert rep.quality == RecordingQuality.FAIL and "truncated_video" in _codes(rep)


def _rewrite_trace(tmp_path: Path, e: TrialManifestEntry, fn) -> None:
    p = tmp_path / "trials" / "t1" / "trace.jsonl"
    lines = p.read_text(encoding="utf-8").splitlines()
    p.write_text("\n".join(fn(lines)) + "\n", encoding="utf-8")
    for a in e.artifacts:
        q = tmp_path / a.relpath
        a.sha256, a.size_bytes = sha256_file(q), q.stat().st_size


def _row(line: str) -> dict[str, Any]:
    return json.loads(line)


@pytest.mark.parametrize(
    ("name", "mut", "code"),
    [
        (
            "nan_state",
            lambda L: [*L[:3], json.dumps({**_row(L[3]), "state": [float("nan"), 0.5]}), *L[4:]],
            "nonfinite_value",
        ),
        (
            "inf_action",
            lambda L: [*L[:4], json.dumps({**_row(L[4]), "action": [float("inf"), 0.1]}), *L[5:]],
            "nonfinite_value",
        ),
        (
            "neg_inf_t",
            lambda L: [*L[:5], json.dumps({**_row(L[5]), "t": float("-inf")}), *L[6:]],
            "nonfinite_value",
        ),
        (
            "decreasing_t",
            lambda L: [*L[:6], json.dumps({**_row(L[6]), "t": 0.0}), *L[7:]],
            "nonmonotonic_timestamps",
        ),
        (
            "extra_column",
            lambda L: [*L[:3], json.dumps({**_row(L[3]), "state": [1.0, 0.5, 9.9]}), *L[4:]],
            "missing_field",
        ),
        (
            "missing_column",
            lambda L: [*L[:3], json.dumps({**_row(L[3]), "action": [0.1]}), *L[4:]],
            "missing_field",
        ),
        (
            "missing_t",
            lambda L: [*L[:3], json.dumps({k: v for k, v in _row(L[3]).items() if k != "t"}), *L[4:]],
            "missing_field",
        ),
        (
            "schema_bump",
            lambda L: [json.dumps({**_row(L[0]), "schema_version": "2.0"}), *L[1:]],
            "schema_mismatch",
        ),
        (
            "no_schema_version",
            lambda L: [json.dumps({k: v for k, v in _row(L[0]).items() if k != "schema_version"}), *L[1:]],
            "schema_mismatch",
        ),
        ("garbage_line", lambda L: [*L[:3], "{not json", *L[3:]], "schema_mismatch"),
        ("no_header", lambda L: L[1:], "schema_mismatch"),
        ("string_nan_token", lambda L: [*L[:3], L[3].replace("0.5", "NaN"), *L[4:]], "nonfinite_value"),
    ],
)
def test_trace_defect_classes_are_each_detected_and_fail(tmp_path: Path, name, mut, code) -> None:
    e = _entry(tmp_path)
    _rewrite_trace(tmp_path, e, mut)
    rep = qa_trial(tmp_path, e)
    assert rep.quality == RecordingQuality.FAIL, name
    assert code in _codes(rep), (name, _codes(rep))
    assert rep.accepted is False


def test_nonfinite_does_not_crash_and_is_not_swallowed_by_float_cast(tmp_path: Path) -> None:
    e = _entry(tmp_path)
    p = tmp_path / "trials" / "t1" / "trace.jsonl"
    txt = p.read_text(encoding="utf-8").replace('"action": [0.1, -0.1]', '"action": [Infinity, -0.1]', 1)
    p.write_text(txt, encoding="utf-8")
    assert "Infinity" in txt
    for a in e.artifacts:
        q = tmp_path / a.relpath
        a.sha256, a.size_bytes = sha256_file(q), q.stat().st_size
    assert "nonfinite_value" in _codes(qa_trial(tmp_path, e))


def test_header_only_trace_must_be_quality_fail(tmp_path: Path) -> None:
    e = _entry(tmp_path)
    _rewrite_trace(tmp_path, e, lambda L: L[:1])
    rep = qa_trial(tmp_path, e)
    assert rep.quality == RecordingQuality.FAIL and rep.accepted is False


def test_missing_video_and_trace_fail(tmp_path: Path) -> None:
    e = _entry(tmp_path)
    (tmp_path / "trials" / "t1" / "video.mp4").unlink()
    assert "missing_video" in _codes(qa_trial(tmp_path, e))
    (tmp_path / "trials" / "t1" / "trace.jsonl").unlink()
    r = qa_trial(tmp_path, e)
    assert r.quality == RecordingQuality.FAIL


def test_hash_mismatch_detected_when_bytes_change_after_recording(tmp_path: Path) -> None:
    e = _entry(tmp_path)
    p = tmp_path / "trials" / "t1" / "trace.jsonl"
    p.write_bytes(p.read_bytes() + b" ")  # whitespace-only change
    assert "hash_mismatch" in _codes(qa_trial(tmp_path, e))


def test_duplicate_trial_ids_in_manifest_detected(tmp_path: Path) -> None:
    from robotevalops.recording.manifest import build_manifest, validate_manifest
    from robotevalops.schemas import Provenance

    e = _entry(tmp_path)
    m = build_manifest(
        session_id="s",
        provenance=Provenance.SIMULATION,
        backend="b",
        task_id="t",
        rubric_version="rubric-v1",
        trials=[e, e.model_copy(deep=True)],
    )
    flags = validate_manifest(m)
    assert any(f.code == QACode.DUPLICATE_ID and f.severity.value == "error" for f in flags)


def test_quarantine_copies_and_never_deletes_sources(tmp_path: Path) -> None:
    e = _entry(tmp_path, n=40)
    v = tmp_path / "trials" / "t1" / "video.mp4"
    v.write_bytes(v.read_bytes()[:200])
    before = {p: sha256_file(p) for p in tmp_path.rglob("*") if p.is_file()}
    rep = qa_trial(tmp_path, e)
    q1, refs = quarantine_trial(tmp_path, "t1", rep)
    q2, _ = quarantine_trial(tmp_path, "t1", rep)  # repeat is safe
    assert refs and all(r.status == ArtifactStatus.QUARANTINED for r in refs)
    assert v.is_file() and sha256_file(v) == before[v]
    for p, h in before.items():
        assert p.is_file() and sha256_file(p) == h
    assert q1.quality == RecordingQuality.FAIL and q2.quality == RecordingQuality.FAIL  # quarantine != fixed
    # hostile relpath inside a report cannot make quarantine write/copy outside the run dir
    from robotevalops.schemas import QAFlag, QAReport, Severity

    evil = QAReport(
        subject="t1",
        flags=[
            QAFlag(
                code=QACode.MISSING_ARTIFACT,
                severity=Severity.ERROR,
                message="x",
                subject="t1",
                evidence={"relpath": "../escape.txt"},
            )
        ],
    )
    with pytest.raises(PathTraversalError):
        quarantine_trial(tmp_path, "t1", evil)


# ------------------------------------------------------------------------------------ pipeline gap
def _mock_cli_session(tmp_path: Path):
    home = tmp_path / "home"
    cfg = Path(__file__).resolve().parents[2] / "configs" / "eval_smoke_mock.yaml"
    r = cli.invoke(
        app, ["session", "create", "--name", "v", "--config", str(cfg), "--home", str(home), "--json"]
    )
    sid = json.loads(r.output)["session_id"]
    assert cli.invoke(app, ["session", "plan", sid, "--home", str(home)]).exit_code == 0
    assert cli.invoke(app, ["session", "run", sid, "--home", str(home)]).exit_code == 0
    return home, sid, EvalService(home)


def test_data_validate_after_session_run_works_or_fails_cleanly(tmp_path: Path) -> None:
    home, sid, _ = _mock_cli_session(tmp_path)
    r = cli.invoke(app, ["data", "validate", str(home / "runs" / sid)])
    assert r.exception is None or isinstance(r.exception, SystemExit), repr(r.exception)
    assert r.exit_code in (0, 1, 2)


def test_corrupt_recording_is_not_counted_as_autonomous_success_after_data_validate(tmp_path: Path) -> None:
    home, sid, svc = _mock_cli_session(tmp_path)
    ok = [t for t in svc.list_trials(sid) if t.task_outcome.value == "success"]
    assert ok
    base = svc.run_dir(sid)
    for t in ok:
        v = svc.trial_dir(sid, t.trial_id) / "video.mp4"
        v.write_bytes(v.read_bytes()[:50])  # destroy every successful trial's video after the run
    cli.invoke(
        app, ["session", "export-manifest", sid, "--home", str(home), "--out", str(base / "manifest.json")]
    )
    v = cli.invoke(app, ["data", "validate", str(base), "--json"])
    assert v.exit_code == 1, v.output  # QA does see the damage ...
    rep = json.loads(cli.invoke(app, ["report", "metrics", sid, "--home", str(home), "--json"]).output)
    assert rep["overall"]["autonomous_successes"] == 0  # ... but metrics still count them
