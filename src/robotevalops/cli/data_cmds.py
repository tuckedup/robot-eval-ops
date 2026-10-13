"""`robotevalops data ...`: validate, quarantine, package, upload, download, verify, faults.

No network call is ever made unless `--store s3` is given explicitly. The tool never creates buckets.
Exit codes: 0 ok; 1 QA errors / integrity or transfer failures / failed fault cases; 2 usage or
expected errors (missing manifest, refused S3, ...).
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer

from robotevalops.errors import RobotEvalOpsError
from robotevalops.qa.quarantine import quarantine_trial
from robotevalops.qa.trial_qa import qa_trial
from robotevalops.recording.manifest import read_manifest, validate_manifest, write_manifest
from robotevalops.schemas import (
    ArtifactStatus,
    QAFlag,
    QAReport,
    RecordingQuality,
    RunManifest,
    Severity,
    TrialState,
)
from robotevalops.storage.base import ArtifactStore
from robotevalops.storage.local import LocalArtifactStore
from robotevalops.storage.package import build_package, download_run, upload_run, verify_run
from robotevalops.util import atomic_write_text, get_home

app = typer.Typer(
    help="data commands: QA, quarantine, packaging, storage, fault injection", no_args_is_help=True
)

RunDirArg = typer.Argument(..., help="Session run directory (runs/<session_id>/)")
JsonOpt = typer.Option(False, "--json", help="Machine-readable JSON output")


def _emit(payload: dict[str, Any], as_json: bool, human: str) -> None:
    typer.echo(json.dumps(payload, indent=2, default=str) if as_json else human)


def _guard(fn: Callable[[], int]) -> None:
    try:
        code = fn()
    except (RobotEvalOpsError, OSError, json.JSONDecodeError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    if code:
        raise typer.Exit(code)


def _make_store(store: str, store_root: Path | None, bucket: str | None, prefix: str) -> ArtifactStore:
    if store == "local":
        return LocalArtifactStore(store_root or get_home() / "store")
    if store == "s3":
        if not bucket:
            raise RobotEvalOpsError(
                "--store s3 requires --bucket (an existing bucket you own); the tool never creates buckets"
            )
        from robotevalops.storage.s3 import S3ArtifactStore

        return S3ArtifactStore(bucket, prefix)
    raise RobotEvalOpsError(f"unknown --store {store!r}; use 'local' (default) or 's3'")


def _find_home(run_dir: Path, home: Path | None) -> Path | None:
    """Home with robotevalops.db: --home, else <run_dir>/../.. (runs/<id>), else $ROBOTEVALOPS_HOME."""
    cands = [home] if home else [run_dir.resolve().parent.parent, get_home()]
    return next((c for c in cands if c and (c / "robotevalops.db").is_file()), None)


def _open_service(home: Path | None) -> Any | None:
    if home is None:
        return None
    from robotevalops.core.service import EvalService

    return EvalService(home)


def _load_manifest(run_dir: Path, svc: Any | None, session_id: str) -> RunManifest:
    path = run_dir / "manifest.json"
    if path.is_file():
        return read_manifest(path)
    if svc is None:
        raise RobotEvalOpsError(
            f"{path} not found and no database was found to rebuild it from. Run `robotevalops session "
            "export-manifest <session_id> --out <run_dir>/manifest.json`, or pass --home pointing at the "
            "data root that holds robotevalops.db"
        )
    manifest = svc.export_manifest(session_id)
    write_manifest(path, manifest)
    return manifest


def _merge_manifest_flags(reports: list[QAReport], mflags: list[QAFlag]) -> list[QAReport]:
    """Fold manifest-level flags (e.g. duplicate trial ids) into the matching trial's report."""
    out = []
    for r in reports:
        have = {(f.code, f.message) for f in r.flags}
        extra = [f for f in mflags if f.subject == r.subject and (f.code, f.message) not in have]
        if extra:
            r = r.model_copy(deep=True)
            r.flags.extend(extra)
            if any(f.severity == Severity.ERROR for f in extra):
                r.accepted = False
                r.rejection_reasons.append(
                    "QA errors present: " + ", ".join(sorted({f.code.value for f in extra}))
                )
        out.append(r)
    return out


_RANK = {RecordingQuality.PASS: 0, RecordingQuality.FLAGGED: 1, RecordingQuality.FAIL: 2}


def _persist_quality(svc: Any, reports: list[QAReport]) -> tuple[list[str], list[str]]:
    """Write recording_quality + flag codes via the public EvalService API. Duplicate trial ids get the
    worst quality. Returns (recorded trial ids, errors)."""
    worst: dict[str, tuple[RecordingQuality, list[str]]] = {}
    for r in reports:
        q, codes = worst.get(r.subject, (RecordingQuality.PASS, []))
        worst[r.subject] = (
            max(q, r.quality, key=lambda x: _RANK[x]),
            list(dict.fromkeys([*codes, *(f.code.value for f in r.flags)])),
        )
    params = inspect.signature(svc.set_recording_quality).parameters
    extra: dict[str, str] = {}
    if "actor" in params:
        extra["actor"] = "data-validate"
    if "reason" in params:
        extra["reason"] = "re-run of data validate"
    done: list[str] = []
    errors: list[str] = []
    for tid, (quality, codes) in worst.items():
        try:
            svc.set_recording_quality(tid, quality, codes, **extra)
            done.append(tid)
        except RobotEvalOpsError as exc:
            errors.append(f"{tid}: could not record quality {quality.value}: {exc}")
    return done, errors


@app.command()
def validate(
    run_dir: Path = RunDirArg,
    require_video: bool = typer.Option(True, "--require-video/--no-require-video"),
    home: Path | None = typer.Option(None, "--home", help="Data root holding robotevalops.db"),
    session_id: str | None = typer.Option(None, "--session-id", help="Default: run directory name"),
    json_out: bool = JsonOpt,
) -> None:
    """Run QA on every trial; write qa/<trial_id>.qa.json and, when a database is found, record
    recording_quality + QA flag codes per trial (so metrics see QA failures). Exit 1 on QA errors."""

    def go() -> int:
        sid = session_id or run_dir.resolve().name
        svc = _open_service(_find_home(run_dir, home))
        manifest = _load_manifest(run_dir, svc, sid)
        mflags = validate_manifest(manifest)
        terminal = {TrialState.COMPLETED, TrialState.FAILED, TrialState.ABORTED}
        skipped = [t.trial_id for t in manifest.trials if t.state not in terminal]  # nothing recorded yet
        reports = _merge_manifest_flags(
            [
                qa_trial(run_dir, t, require_video=require_video)
                for t in manifest.trials
                if t.state in terminal
            ],
            mflags,
        )
        for r in reports:
            atomic_write_text(run_dir / "qa" / f"{r.subject}.qa.json", r.model_dump_json(indent=2) + "\n")
        recorded: list[str] = []
        db_errors: list[str] = []
        if svc is not None:
            recorded, db_errors = _persist_quality(svc, reports)
        n_err = sum(f.severity == Severity.ERROR for r in reports for f in r.flags)
        m_err = [
            f
            for f in mflags
            if f.severity == Severity.ERROR and not any(f.subject == r.subject for r in reports)
        ]
        payload = {
            "run_dir": str(run_dir),
            "session_id": sid,
            "trials": len(reports),
            "skipped_not_attempted": skipped,
            "database_recorded": svc is not None,
            "recorded_trials": recorded,
            "database_errors": db_errors,
            "manifest_flags": [f.model_dump(mode="json") for f in mflags],
            "reports": [
                {
                    "trial_id": r.subject,
                    "quality": r.quality.value,
                    "accepted": r.accepted,
                    "rejection_reasons": r.rejection_reasons,
                    "flags": [f.model_dump(mode="json") for f in r.flags],
                }
                for r in reports
            ],
            "error_count": n_err + len(m_err) + len(db_errors),
        }
        lines = [
            f"{r.subject}: quality={r.quality.value} accepted={r.accepted}"
            + "".join(f"\n  [{f.severity.value}] {f.code.value}: {f.message}" for f in r.flags)
            for r in reports
        ]
        lines += [f"manifest [{f.severity.value}] {f.code.value}: {f.message}" for f in mflags]
        lines += [f"database error: {e}" for e in db_errors]
        lines.append(
            f"recorded recording_quality for {len(recorded)} trial(s) in the database"
            if svc is not None
            else "NOTE: no database found (use --home); results are NOT recorded in the database"
        )
        _emit(payload, json_out, "\n".join(lines))
        return 1 if payload["error_count"] else 0

    _guard(go)


@app.command()
def quarantine(
    run_dir: Path = RunDirArg,
    trial: str | None = typer.Option(None, "--trial", help="Only this trial_id"),
    json_out: bool = JsonOpt,
) -> None:
    """Re-run QA and COPY offending artifacts to quarantine/<trial_id>/ (originals untouched)."""

    def go() -> int:
        manifest = read_manifest(run_dir / "manifest.json")
        out = []
        for t in manifest.trials:
            if t.state not in (TrialState.COMPLETED, TrialState.FAILED, TrialState.ABORTED):
                continue
            if trial and t.trial_id != trial:
                continue
            rep = qa_trial(run_dir, t)
            q, _ = quarantine_trial(run_dir, t.trial_id, rep) if rep.quality.value == "fail" else (rep, [])
            if q.quarantined:
                atomic_write_text(
                    run_dir / "qa" / f"{t.trial_id}.qa.json", q.model_dump_json(indent=2) + "\n"
                )
            out.append({"trial_id": t.trial_id, "quality": q.quality.value, "quarantined": q.quarantined})
        _emit(
            {"results": out},
            json_out,
            "\n".join(f"{o['trial_id']}: {o['quality']} quarantined={o['quarantined']}" for o in out),
        )
        return 0

    _guard(go)


@app.command()
def package(
    run_dir: Path = RunDirArg,
    session_id: str | None = typer.Option(None, "--session-id"),
    json_out: bool = JsonOpt,
) -> None:
    """List what would be packaged (hashes, sizes) and what is blocked (credentials, symlinks, temp files)."""

    def go() -> int:
        rep = build_package(run_dir, session_id or run_dir.resolve().name)
        _emit(
            rep.to_dict(),
            json_out,
            f"{len(rep.artifacts)} artifact(s), {len(rep.blocked)} blocked\n"
            + "\n".join(f"  blocked {b['relpath']}: {b['reason']}" for b in rep.blocked),
        )
        return 0

    _guard(go)


STORE = typer.Option("local", "--store", help="local (default) or s3; s3 is used ONLY when given explicitly")
BUCKET = typer.Option(None, "--bucket", help="Existing S3 bucket you own (--store s3)")
PREFIX = typer.Option("", "--prefix", help="Key prefix inside the bucket (--store s3)")
ROOT = typer.Option(None, "--store-root", help="Local store root (default $ROBOTEVALOPS_HOME/store)")


@app.command()
def upload(
    run_dir: Path = RunDirArg,
    session_id: str | None = typer.Option(None, "--session-id"),
    store: str = STORE,
    bucket: str | None = BUCKET,
    prefix: str = PREFIX,
    store_root: Path | None = ROOT,
    json_out: bool = JsonOpt,
) -> None:
    """Upload a run to runs/<session_id>/ (resumable; identical artifacts skipped). Exit 1 on any failure."""

    def go() -> int:
        st = _make_store(store, store_root, bucket, prefix)
        rep = upload_run(st, run_dir, session_id or run_dir.resolve().name)
        _emit(
            rep.to_dict(),
            json_out,
            f"uploaded/transferred {rep.transferred}, skipped identical "
            f"{rep.skipped_identical}, failed {rep.count(ArtifactStatus.FAILED)}"
            + "".join(f"\n  {e}" for e in rep.errors),
        )
        return 0 if rep.ok else 1

    _guard(go)


@app.command()
def download(
    session_id: str = typer.Argument(...),
    dest: Path = typer.Argument(...),
    store: str = STORE,
    bucket: str | None = BUCKET,
    prefix: str = PREFIX,
    store_root: Path | None = ROOT,
    json_out: bool = JsonOpt,
) -> None:
    """Download runs/<session_id>/ into dest and recompute SHA-256 where the store recorded one."""

    def go() -> int:
        rep = download_run(_make_store(store, store_root, bucket, prefix), session_id, dest)
        _emit(
            rep.to_dict(),
            json_out,
            f"downloaded {len(rep.artifacts)} artifact(s), verified {rep.verified}, "
            f"blocked {len(rep.blocked)}" + "".join(f"\n  {e}" for e in rep.errors),
        )
        return 0 if rep.ok and not rep.blocked else 1

    _guard(go)


@app.command()
def verify(
    run_dir: Path = RunDirArg,
    session_id: str | None = typer.Option(None, "--session-id"),
    store: str = STORE,
    bucket: str | None = BUCKET,
    prefix: str = PREFIX,
    store_root: Path | None = ROOT,
    json_out: bool = JsonOpt,
) -> None:
    """Download each object and recompute SHA-256 against the local file. Exit 1 on mismatch/missing."""

    def go() -> int:
        rep = verify_run(
            _make_store(store, store_root, bucket, prefix), run_dir, session_id or run_dir.resolve().name
        )
        agr = rep.checksum_agreement
        _emit(
            rep.to_dict(),
            json_out,
            f"verified {rep.verified}/{rep.transferred} transferred "
            f"(checksum agreement {'n/a' if agr is None else f'{agr:.3f}'})"
            + "".join(f"\n  {e}" for e in rep.errors),
        )
        return 0 if rep.ok and rep.verified == len(rep.artifacts) else 1

    _guard(go)


@app.command()
def faults(
    out_dir: Path = typer.Option(Path("docs"), "--out-dir", help="Where fault-injection-report.{md,json} go"),
    workdir: Path | None = typer.Option(None, "--workdir", help="Scratch dir (default: temp)"),
    json_out: bool = JsonOpt,
) -> None:
    """Execute fault cases F01-F10 and write the report. Exit 1 unless all ten executed and passed."""
    from robotevalops.faults.registry import run_all
    from robotevalops.faults.report import write_report

    def go() -> int:
        results = run_all(workdir)
        payload = write_report(results, out_dir / "fault-injection-report.md")
        s = payload["summary"]
        _emit(
            payload,
            json_out,
            f"{s['executed']}/{s['total']} executed, {s['passed']} passed"
            + (f"; FAILED: {s['failed']}" if s["failed"] else "")
            + (f"; NOT EXECUTED: {s['not_executed']}" if s["not_executed"] else "")
            + f"\nreport: {out_dir / 'fault-injection-report.md'}",
        )
        return 0 if s["passed"] == s["total"] else 1

    _guard(go)
