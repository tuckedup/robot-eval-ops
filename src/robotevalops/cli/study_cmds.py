"""`robotevalops study ...`: the pre-specified physics stress study (pilot, freeze, evaluate, report)."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from robotevalops.errors import RobotEvalOpsError
from robotevalops.study import stress

app = typer.Typer(help="pre-specified physics stress study", no_args_is_help=True)
ProtoOpt = typer.Option(Path("docs/stress-study/protocol_stress_v1.yaml"), "--protocol", help="protocol YAML")
WorkersOpt = typer.Option(6, "--workers", min=1, help="parallel session processes")


def _fail(e: Exception) -> None:
    typer.echo(f"error: {e}", err=True)
    raise typer.Exit(2)


@app.command("pilot")
def pilot(
    home: Path = typer.Option(..., "--home", help="data root for the PILOT (separate from the evaluation)"),
    protocol: Path = ProtoOpt,
    workers: int = WorkersOpt,
) -> None:
    """Run the feasibility pilot (tuning seeds). Its results are never reported."""
    try:
        if stress.frozen_path(protocol).exists():
            raise RobotEvalOpsError("protocol already frozen; the pilot belongs before freezing")
        ids = stress.plan_stage(home, protocol, "pilot")
        codes = stress.run_sessions(home, ids, workers)
        out = stress.pilot_findings(home, protocol) | {"session_exit_codes": codes}
        typer.echo(json.dumps(out, indent=2))
        if not out["clean"]:
            raise typer.Exit(1)
    except RobotEvalOpsError as e:
        _fail(e)


@app.command("freeze")
def freeze(
    pilot_home: Path = typer.Option(..., "--pilot-home"),
    protocol: Path = ProtoOpt,
) -> None:
    """Freeze the protocol (writes <protocol>.frozen.json with file hashes) after a clean pilot."""
    try:
        typer.echo(json.dumps(stress.freeze(protocol, pilot_home), indent=2))
    except RobotEvalOpsError as e:
        _fail(e)


@app.command("run")
def run(
    home: Path = typer.Option(..., "--home", help="data root for the held-out EVALUATION"),
    protocol: Path = ProtoOpt,
    workers: int = WorkersOpt,
) -> None:
    """Run the held-out evaluation. Refuses unless the protocol still matches its frozen hashes."""
    try:
        rec = stress.require_frozen(protocol)
        stress.check_seeds_disjoint(stress.load_protocol(protocol))
        ids = stress.plan_stage(home, protocol, "evaluation")
        codes = stress.run_sessions(home, ids, workers)
        typer.echo(
            json.dumps(
                {"frozen_sha256": rec["combined_sha256"], "sessions": ids, "exit_codes": codes}, indent=2
            )
        )
        if any(codes.values()):
            raise typer.Exit(1)
    except RobotEvalOpsError as e:
        _fail(e)


@app.command("report")
def report(
    home: Path = typer.Option(..., "--home"),
    out: Path = typer.Option(..., "--out"),
    protocol: Path = ProtoOpt,
    stage: str = typer.Option("evaluation", "--stage"),
) -> None:
    """Write results.json, report.md and the envelope plot for a stage."""
    try:
        proto = stress.load_protocol(protocol)
        res = stress.analyze_stage(home, protocol, stage)
        if stage == "evaluation":
            res["frozen"] = stress.require_frozen(protocol)
        out.mkdir(parents=True, exist_ok=True)
        (out / "results.json").write_text(json.dumps(res, indent=2, default=str) + "\n", encoding="utf-8")
        (out / "report.md").write_text(stress.render_report(res, proto), encoding="utf-8")
        stress.plot_envelope(res, out / "failure_envelope.png")
        typer.echo(
            json.dumps(res["denominators"] | {"failure_categories": res["failure_categories"]}, indent=2)
        )
    except RobotEvalOpsError as e:
        _fail(e)
