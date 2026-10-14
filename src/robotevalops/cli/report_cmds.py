"""`robotevalops report ...` commands (eval/reporting). Every command supports --home and exits non-zero on
failure; data commands support --json. Only the public EvalService API is used."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any

import typer

from robotevalops import scoring
from robotevalops.core.service import EvalService
from robotevalops.errors import RobotEvalOpsError
from robotevalops.metrics.compare import compare_controllers
from robotevalops.metrics.compute import compute_metrics
from robotevalops.reporting.export import ALL_FORMATS, export_summary
from robotevalops.schemas import Intervention, ScoreSource, TaskOutcome, TrialRecord
from robotevalops.util import RUBRIC_VERSION

app = typer.Typer(
    help="report commands: scoring, metrics, comparison, exports, dashboard", no_args_is_help=True
)

HomeOpt = typer.Option(None, "--home", help="Data root (default $ROBOTEVALOPS_HOME or ./data)")
JsonOpt = typer.Option(False, "--json", help="Print machine-readable JSON")


def _emit(data: Any, as_json: bool, text: str) -> None:
    typer.echo(json.dumps(data, indent=2, default=str) if as_json else text)


def _guarded(fn: Callable[..., None]) -> Callable[..., None]:
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> None:
        try:
            fn(*args, **kwargs)
        except (RobotEvalOpsError, ValueError) as e:
            name = type(e).__name__
            if kwargs.get("as_json"):
                typer.echo(json.dumps({"error": name, "message": str(e)}))
            else:
                typer.echo(f"error: {name}: {e}", err=True)
            raise typer.Exit(1) from e

    return wrapper


def _trials(svc: EvalService, session_ids: list[str]) -> list[TrialRecord]:
    out: list[TrialRecord] = []
    for sid in session_ids:
        out += svc.list_trials(sid)
    return out


@app.command("score")
@_guarded
def score(
    trial_id: str = typer.Argument(..., help="COMPLETED, unscored trial id"),
    outcome: TaskOutcome = typer.Option(..., "--outcome", help="success | failure"),
    scorer: str = typer.Option(..., "--scorer", help="Human scorer name (required)"),
    intervention: Intervention = typer.Option(..., "--intervention", help="none | assisted"),
    source: ScoreSource = typer.Option(ScoreSource.OPERATOR_VIDEO, "--source"),
    rubric_version: str = typer.Option(RUBRIC_VERSION, "--rubric-version"),
    home: Path | None = HomeOpt,
    as_json: bool = JsonOpt,
) -> None:
    """Apply the FIRST score to a completed trial (operator video scoring)."""
    svc = EvalService(home)
    t = scoring.apply_score(
        svc,
        trial_id,
        outcome,
        scorer=scorer,
        intervention=intervention,
        source=source,
        rubric_version=rubric_version,
    )
    _emit(
        t.model_dump(mode="json"),
        as_json,
        f"scored {trial_id}: {t.task_outcome.value} (intervention {t.intervention.value}, by {scorer})",
    )


@app.command("edit-score")
@_guarded
def edit_score(
    trial_id: str = typer.Argument(...),
    outcome: TaskOutcome = typer.Option(..., "--outcome"),
    editor: str = typer.Option(..., "--editor"),
    reason: str = typer.Option(..., "--reason", help="Mandatory, non-empty"),
    intervention: Intervention = typer.Option(..., "--intervention"),
    source: ScoreSource = typer.Option(ScoreSource.OPERATOR_VIDEO, "--source"),
    rubric_version: str = typer.Option(RUBRIC_VERSION, "--rubric-version"),
    home: Path | None = HomeOpt,
    as_json: bool = JsonOpt,
) -> None:
    """Audited edit of an existing score (before/after values and reason are logged)."""
    svc = EvalService(home)
    e = scoring.edit_score(
        svc,
        trial_id,
        outcome,
        editor=editor,
        reason=reason,
        intervention=intervention,
        source=source,
        rubric_version=rubric_version,
    )
    _emit(
        e.model_dump(mode="json"),
        as_json,
        f"edited {trial_id}: {e.before_outcome.value} -> {e.after_outcome.value} by {editor} ({reason})",
    )


@app.command("unscored")
@_guarded
def unscored(
    session_id: str = typer.Argument(...), home: Path | None = HomeOpt, as_json: bool = JsonOpt
) -> None:
    """List COMPLETED trials that still need a score."""
    svc = EvalService(home)
    ts = scoring.list_unscored(svc, session_id)
    _emit(
        [t.trial_id for t in ts], as_json, "\n".join(t.trial_id for t in ts) or "no unscored completed trials"
    )


@app.command("agreement")
@_guarded
def agreement(
    csv_path: Path = typer.Argument(..., help="docs/templates/scoring-agreement.csv format"),
    as_json: bool = JsonOpt,
) -> None:
    """Percent agreement and Cohen's kappa between two independent human scorers (from the CSV only)."""
    r = scoring.agreement_from_csv(csv_path)
    _emit(
        r.model_dump(mode="json"),
        as_json,
        f"n={r.n} agreement={r.percent_agreement} kappa={r.cohen_kappa}\n{r.note}",
    )


@app.command("metrics")
@_guarded
def metrics(
    session_ids: list[str] = typer.Argument(..., help="One or more session ids"),
    home: Path | None = HomeOpt,
    as_json: bool = JsonOpt,
) -> None:
    """Metrics with contracts section 5 denominators (planned/attempted/.../evaluable, Wilson 95% CIs)."""
    svc = EvalService(home)
    rep = compute_metrics(_trials(svc, session_ids))
    if as_json:
        typer.echo(json.dumps(rep.model_dump(mode="json"), indent=2))
        return
    g = rep.overall
    if rep.banner:
        typer.echo(f"*** {rep.banner} ***")
    typer.echo(
        f"provenance: {', '.join(rep.provenances)}; controller types: {', '.join(rep.controller_types)}"
    )
    typer.echo(
        f"planned {g.planned} | attempted {g.attempted} | completed {g.completed} | failed {g.failed} | "
        f"aborted {g.aborted} | unscored {g.unscored} | evaluable {g.evaluable}"
    )
    typer.echo(f"autonomous success / attempted : {g.success_per_attempt.fmt()}")
    typer.echo(f"autonomous success / evaluable : {g.success_per_evaluable.fmt()}")
    typer.echo(
        f"intervention rate {g.intervention_rate.fmt()} | infra-abort rate {g.infra_abort_rate.fmt()} | "
        f"recording pass rate {g.recording_pass_rate.fmt()}"
    )
    for w in rep.warnings:
        typer.echo(f"warning: {w}")


@app.command("compare")
@_guarded
def compare(
    session_ids: list[str] = typer.Argument(...),
    a: str = typer.Option(..., "--a", help="controller_id A"),
    b: str = typer.Option(..., "--b", help="controller_id B"),
    home: Path | None = HomeOpt,
    as_json: bool = JsonOpt,
) -> None:
    """Paired comparison of two controllers (discordant counts, exact McNemar p; descriptive only)."""
    svc = EvalService(home)
    c = compare_controllers(_trials(svc, session_ids), a, b)
    if as_json:
        typer.echo(json.dumps(c.model_dump(mode="json"), indent=2))
        return
    typer.echo(f"{a} vs {b} (provenance {', '.join(c.provenances)})")
    for cell in [c.overall, *c.by_condition]:
        p = "n/a" if cell.p_value_exact_mcnemar is None else f"{cell.p_value_exact_mcnemar:.4f}"
        typer.echo(
            f"{cell.condition}: pairs {cell.pairs} both {cell.both} A-only {cell.a_only} "
            f"B-only {cell.b_only} neither {cell.neither} exact McNemar p {p}"
        )
    for u in c.unpaired:
        typer.echo(f"unpaired: {u.condition} #{u.trial_index}: {u.reason}")
    typer.echo(c.caveat)


def _out_dir(svc: EvalService, session_ids: list[str], out_dir: Path | None) -> Path:
    if out_dir is not None:
        return out_dir
    return svc.home / "reports" / (session_ids[0] if len(session_ids) == 1 else "combined")


def _do_export(
    session_ids: list[str], out_dir: Path | None, formats: list[str], home: Path | None, as_json: bool
) -> None:
    svc = EvalService(home)
    out = _out_dir(svc, session_ids, out_dir)
    written = export_summary(svc, session_ids, out, formats=formats)
    _emit(
        {k: str(v) for k, v in written.items()}, as_json, "\n".join(f"{k}: {v}" for k, v in written.items())
    )


@app.command("export")
@_guarded
def export(
    session_ids: list[str] = typer.Argument(...),
    out_dir: Path | None = typer.Option(None, "--out-dir", help="default <home>/reports/<session_id>"),
    fmt: list[str] = typer.Option(list(ALL_FORMATS), "--format", help="md, csv, json, html (repeatable)"),
    home: Path | None = HomeOpt,
    as_json: bool = JsonOpt,
) -> None:
    """Write summary.md/csv/json, plots and report.html."""
    _do_export(session_ids, out_dir, list(fmt), home, as_json)


@app.command("html")
@_guarded
def html(
    session_ids: list[str] = typer.Argument(...),
    out_dir: Path | None = typer.Option(None, "--out-dir"),
    home: Path | None = HomeOpt,
    as_json: bool = JsonOpt,
) -> None:
    """Write the self-contained report.html (plus plots)."""
    _do_export(session_ids, out_dir, ["html"], home, as_json)


@app.command("dashboard")
def dashboard(
    home: Path | None = HomeOpt,
    port: int = typer.Option(8501, "--port"),
    check: bool = typer.Option(False, "--check", help="Print the command instead of launching"),
) -> None:
    """Launch the Streamlit dashboard (read/score only; no robot controls)."""
    import robotevalops.dashboard as dash_pkg

    app_path = Path(dash_pkg.__file__).with_name("app.py")  # never import app.py: it runs Streamlit code
    cmd = [sys.executable, "-m", "streamlit", "run", str(app_path), "--server.port", str(port)]
    env_note = f"ROBOTEVALOPS_HOME={home}" if home else "ROBOTEVALOPS_HOME unset (default ./data)"
    if check:
        typer.echo(env_note)
        typer.echo(" ".join(cmd))
        return
    import os

    env = dict(os.environ)
    if home:
        env["ROBOTEVALOPS_HOME"] = str(Path(home).resolve())
    raise typer.Exit(subprocess.call(cmd, env=env))


@app.command("paired-duration")
@_guarded
def paired_duration(
    controller_a: str = typer.Option(..., "--a", help="controller_id A"),
    controller_b: str = typer.Option(..., "--b", help="controller_id B"),
    out: Path = typer.Option(..., "--out", help="Directory for analysis.json / analysis.md / plots"),
    home: Path | None = HomeOpt,
    session_id: list[str] = typer.Option([], "--session-id", help="Default: every session in the database"),
    as_json: bool = JsonOpt,
) -> None:
    """Paired duration + trade-off analysis of two controllers. READ-ONLY on the source data: the database
    is copied to a temp dir first and every artifact hash is verified before the numbers are used."""
    import shutil
    import tempfile

    from robotevalops.analysis.paired_duration import analyze, render_markdown
    from robotevalops.analysis.plots import plot_scenario_diffs, plot_trajectories
    from robotevalops.util import atomic_write_text, get_home, sha256_file

    src = get_home(home)
    db = src / "robotevalops.db"
    if not db.is_file():
        raise RobotEvalOpsError(f"no robotevalops.db under {src}")
    before = sha256_file(db)
    with tempfile.TemporaryDirectory() as tmp:
        for f in src.glob("robotevalops.db*"):
            shutil.copy2(f, Path(tmp) / f.name)
        svc = EvalService(tmp)
        ids = session_id or [s.session_id for s in svc.list_sessions()]
        trials = _trials(svc, ids)
    mism = []
    for t in trials:
        for a in t.artifacts:
            p = src / "runs" / t.session_id / a.relpath
            if not p.is_file() or (a.sha256 and sha256_file(p) != a.sha256):
                mism.append(f"{t.trial_id}:{a.relpath}")
    if mism:
        raise RobotEvalOpsError(
            f"{len(mism)} artifact(s) missing or hash-mismatched; refusing to analyse: {mism[:5]}"
        )
    params: dict[str, Any] = {
        c: next(
            (
                json.loads(p.read_text(encoding="utf-8"))
                for p in [
                    src / "runs" / t.session_id / a.relpath
                    for t in trials
                    if t.controller_id == c
                    for a in t.artifacts
                    if a.role.value == "config"
                ][:1]
            ),
            {},
        )
        for c in (controller_a, controller_b)
    }
    params = {
        c: {**p.get("spec", {}).get("config", {}), "config_hash": p.get("config_hash")}
        for c, p in params.items()
    }
    res = analyze(trials, controller_a, controller_b, params, run_root=src / "runs")
    out.mkdir(parents=True, exist_ok=True)
    traces = {}
    for c in (controller_a, controller_b):
        t = next(
            t for t in trials if t.controller_id == c and t.condition_name == "nominal" and t.trial_index == 0
        )
        traces[c] = (
            src / "runs" / t.session_id / next(a.relpath for a in t.artifacts if a.role.value == "trace")
        )
    plot_trajectories(
        traces, out / "trajectories_nominal.png", f"Nominal start, trial 0: {controller_a} vs {controller_b}"
    )
    plot_scenario_diffs(res, out / "paired_differences.png")
    data = res.to_dict()
    data["source"] = {
        "home": str(src),
        "db_sha256_before": before,
        "db_sha256_after": sha256_file(db),
        "artifacts_verified": sum(len(t.artifacts) for t in trials),
        "sessions": ids,
    }
    if data["source"]["db_sha256_after"] != before:
        raise RobotEvalOpsError("source database changed during analysis (it must be untouched)")
    atomic_write_text(out / "analysis.json", json.dumps(data, indent=2, default=str) + "\n")
    atomic_write_text(out / "analysis.md", render_markdown(res))
    _emit(data["duration"] if as_json else data, as_json, render_markdown(res))
