"""`robotevalops data ...`: validate, quarantine, package, upload, download, verify, faults.

No network call is ever made unless `--store s3` is given explicitly. The tool never creates buckets.
Exit codes: 0 ok; 1 QA errors / integrity or transfer failures / failed fault cases; 2 usage or
expected errors (missing manifest, refused S3, ...).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer

from robotevalops.errors import RobotEvalOpsError
from robotevalops.qa.quarantine import quarantine_trial
from robotevalops.qa.trial_qa import qa_trial
from robotevalops.recording.manifest import read_manifest, validate_manifest
from robotevalops.schemas import ArtifactStatus, QAReport, Severity
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
    except RobotEvalOpsError as exc:
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


def _qa_all(run_dir: Path, require_video: bool) -> tuple[list[QAReport], list[Any]]:
    manifest = read_manifest(run_dir / "manifest.json")
    reports = [qa_trial(run_dir, t, require_video=require_video) for t in manifest.trials]
    return reports, validate_manifest(manifest)


@app.command()
def validate(
    run_dir: Path = RunDirArg,
    require_video: bool = typer.Option(True, "--require-video/--no-require-video"),
    json_out: bool = JsonOpt,
) -> None:
    """Run QA on every trial in run_dir/manifest.json; writes qa/<trial_id>.qa.json. Exit 1 on QA errors."""

    def go() -> int:
        reports, mflags = _qa_all(run_dir, require_video)
        for r in reports:
            atomic_write_text(run_dir / "qa" / f"{r.subject}.qa.json", r.model_dump_json(indent=2) + "\n")
        n_err = sum(f.severity == Severity.ERROR for r in reports for f in r.flags)
        m_err = [f for f in mflags if f.severity == Severity.ERROR]
        payload = {
            "run_dir": str(run_dir),
            "trials": len(reports),
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
            "error_count": n_err + len(m_err),
        }
        lines = [
            f"{r.subject}: quality={r.quality.value} accepted={r.accepted}"
            + "".join(f"\n  [{f.severity.value}] {f.code.value}: {f.message}" for f in r.flags)
            for r in reports
        ]
        lines += [f"manifest [{f.severity.value}] {f.code.value}: {f.message}" for f in mflags]
        _emit(payload, json_out, "\n".join(lines) or "no trials")
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
