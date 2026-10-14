"""`robotevalops session ...` commands (core). Every command supports --home and --json and exits non-zero on
failure. `run` builds adapters through robotevalops.adapters.registry (Robotics) imported lazily."""

from __future__ import annotations

import json
import sys
from collections import Counter
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any

import typer

from robotevalops.config import load_eval_config
from robotevalops.core.runner import Runner
from robotevalops.core.service import EvalService
from robotevalops.errors import CapabilityUnavailableError, RobotEvalOpsError
from robotevalops.schemas import (
    ControllerSpec,
    Provenance,
    SessionRecord,
    SessionState,
    TrialState,
)

app = typer.Typer(help="session commands", no_args_is_help=True)

HomeOpt = typer.Option(None, "--home", help="Data root (default $ROBOTEVALOPS_HOME or ./data)")
JsonOpt = typer.Option(False, "--json", help="Print machine-readable JSON")


def _emit(data: Any, as_json: bool, text: str) -> None:
    if as_json:
        typer.echo(json.dumps(data, indent=2, default=str))
    else:
        typer.echo(text)


def _dump(model: Any) -> Any:
    return model.model_dump(mode="json")


def _guarded(fn: Callable[..., None]) -> Callable[..., None]:
    """Turn expected errors into a one-line message (JSON when --json) and a non-zero exit code."""

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> None:
        try:
            fn(*args, **kwargs)
        except RobotEvalOpsError as e:
            if kwargs.get("as_json"):
                typer.echo(json.dumps({"error": type(e).__name__, "message": str(e)}))
            else:
                typer.echo(f"error: {type(e).__name__}: {e}", err=True)
            raise typer.Exit(1) from e
        except ValueError as e:
            if kwargs.get("as_json"):
                typer.echo(json.dumps({"error": "ValueError", "message": str(e)}))
            else:
                typer.echo(f"error: {e}", err=True)
            raise typer.Exit(1) from e

    return wrapper


def _registry() -> Any:
    try:
        import importlib

        registry = importlib.import_module("robotevalops.adapters.registry")
    except ImportError as e:
        raise CapabilityUnavailableError(
            "robotevalops.adapters.registry is not available (adapters are provided by the robotics module): "
            f"{e}"
        ) from e
    for fn in ("get_adapter", "get_controller"):
        if not hasattr(registry, fn):
            raise CapabilityUnavailableError(
                f"robotevalops.adapters.registry has no {fn}(); cannot build adapters"
            )
    return registry


def _session_summary(svc: EvalService, s: SessionRecord) -> dict[str, Any]:
    counts = Counter(t.state.value for t in svc.list_trials(s.session_id))
    d = _dump(s)
    d["trial_counts"] = {st.value: counts.get(st.value, 0) for st in TrialState}
    d["planned_total"] = sum(counts.values())
    return d


@app.command()
@_guarded
def create(
    name: str = typer.Option(..., "--name"),
    provenance: Provenance | None = typer.Option(None, "--provenance"),
    backend: str | None = typer.Option(None, "--backend"),
    config: Path | None = typer.Option(
        None, "--config", help="eval config YAML (provides provenance/backend)"
    ),
    purpose: str = typer.Option("evaluation", "--purpose"),
    operator: str = typer.Option("", "--operator"),
    device_id: str | None = typer.Option(None, "--device-id"),
    calibration_ref: str | None = typer.Option(None, "--calibration-ref"),
    notes: str = typer.Option("", "--notes"),
    home: Path | None = HomeOpt,
    as_json: bool = JsonOpt,
) -> None:
    """Create a session (does not plan trials; use `session plan`)."""
    cfg = load_eval_config(config) if config else None
    prov = provenance or (cfg.provenance if cfg else None)
    be = backend or (cfg.backend if cfg else None)
    if prov is None or be is None:
        raise ValueError("give --config, or both --provenance and --backend")
    svc = EvalService(home)
    s = svc.create_session(
        name,
        prov,
        be,
        purpose=purpose,
        operator=operator,
        device_id=device_id,
        calibration_ref=calibration_ref,
        eval_config=cfg,
        notes=notes,
    )
    _emit(_dump(s), as_json, f"created session {s.session_id} ({s.provenance.value}/{s.backend})")


@app.command()
@_guarded
def plan(
    session_id: str = typer.Argument(...),
    config: Path | None = typer.Option(
        None, "--config", help="eval config YAML (default: stored with session)"
    ),
    home: Path | None = HomeOpt,
    as_json: bool = JsonOpt,
) -> None:
    """Plan the deterministic, paired trial schedule."""
    svc = EvalService(home)
    cfg = load_eval_config(config) if config else svc.get_eval_config(session_id)
    if cfg is None:
        raise ValueError("session has no stored eval config; pass --config")
    trials = svc.plan_trials(session_id, cfg)
    _emit(
        {"session_id": session_id, "planned": len(trials), "trial_ids": [t.trial_id for t in trials]},
        as_json,
        f"planned {len(trials)} trials for session {session_id}",
    )


@app.command("list")
@_guarded
def list_(home: Path | None = HomeOpt, as_json: bool = JsonOpt) -> None:
    """List sessions."""
    svc = EvalService(home)
    rows = [_session_summary(svc, s) for s in svc.list_sessions()]
    text = (
        "\n".join(
            f"{r['session_id']}  {r['state']:<9} {r['provenance']}/{r['backend']}  trials={r['planned_total']}  {r['name']}"  # noqa: E501
            for r in rows
        )
        or "(no sessions)"
    )
    _emit(rows, as_json, text)


@app.command()
@_guarded
def show(
    session_id: str = typer.Argument(...),
    trials: bool = typer.Option(False, "--trials", help="include every trial"),
    home: Path | None = HomeOpt,
    as_json: bool = JsonOpt,
) -> None:
    """Show a session with trial counts by state."""
    svc = EvalService(home)
    d = _session_summary(svc, svc.get_session(session_id))
    lines = [f"{k}: {v}" for k, v in d.items() if k not in ("software", "task")]
    if trials:
        ts = svc.list_trials(session_id)
        d["trials"] = [_dump(t) for t in ts]
        lines += [
            f"  #{t.schedule_position:03d} {t.trial_id} {t.controller_id} {t.condition_name}[{t.trial_index}] "  # noqa: E501
            f"{t.state.value} outcome={t.task_outcome.value}"
            for t in ts
        ]
    _emit(d, as_json, "\n".join(lines))


@app.command()
@_guarded
def preflight(
    session_id: str = typer.Argument(...),
    home: Path | None = HomeOpt,
    as_json: bool = JsonOpt,
) -> None:
    """Run the adapter's non-moving preflight; on success the session becomes READY."""
    svc = EvalService(home)
    s = svc.get_session(session_id)
    if s.state in (SessionState.PLANNED, SessionState.READY):
        svc.transition_session(session_id, SessionState.PREFLIGHT)
    elif s.state != SessionState.PREFLIGHT:
        raise ValueError(f"cannot preflight a {s.state.value} session")
    reg = _registry()
    adapter = reg.get_adapter(s.backend, s)
    try:
        result = adapter.preflight()
    finally:
        adapter.close()
    checks = [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in result.checks]
    if result.ok:
        svc.mark_preflight_passed(session_id)
    _emit(
        {"session_id": session_id, "ok": result.ok, "checks": checks},
        as_json,
        "\n".join(f"[{'ok' if c['ok'] else 'FAIL'}] {c['name']} {c['detail']}" for c in checks)
        + f"\npreflight {'passed' if result.ok else 'FAILED'}",
    )
    if not result.ok:
        raise typer.Exit(2)


@app.command()
@_guarded
def ack(
    session_id: str = typer.Argument(...),
    operator: str = typer.Option(..., "--operator"),
    home: Path | None = HomeOpt,
    as_json: bool = JsonOpt,
) -> None:
    """Per-session operator acknowledgement (required for physical hardware)."""
    s = EvalService(home).acknowledge_operator(session_id, operator)
    _emit(_dump(s), as_json, f"operator {operator} acknowledged session {session_id}")


@app.command()
@_guarded
def run(
    session_id: str = typer.Argument(...),
    max_trials: int | None = typer.Option(None, "--max-trials", min=1),
    home: Path | None = HomeOpt,
    as_json: bool = JsonOpt,
) -> None:
    """Run the planned trials. Refuses hardware sessions without ack and sessions needing a fresh preflight."""  # noqa: E501
    svc = EvalService(home)
    s = svc.get_session(session_id)
    # fail early (before touching the registry) on the hardware / preflight gates
    from robotevalops.errors import HardwareRefusedError, PreflightFailedError

    if s.provenance == Provenance.PHYSICAL_HARDWARE and s.operator_ack_at is None:
        raise HardwareRefusedError(
            f"session {session_id} is physical_hardware and has no operator acknowledgement; run "
            f"`robotevalops session ack {session_id} --operator <name>`"
        )
    if s.requires_fresh_preflight:
        raise PreflightFailedError(
            f"session {session_id} requires a fresh preflight; run `robotevalops session preflight {session_id}`"  # noqa: E501
        )
    reg = _registry()

    def controller_factory(spec: ControllerSpec) -> Any:
        return reg.get_controller(spec, s.backend)

    from robotevalops.integration import make_hooks

    qa_hook, manifest_hook = make_hooks(svc)  # recording QA must always reach the DB
    runner = Runner(
        svc,
        lambda sess: reg.get_adapter(sess.backend, sess),
        controller_factory,
        qa_hook=qa_hook,
        manifest_hook=manifest_hook,
        # physical-port leases, shared with `robot teleop|record|rollout`
        device_keys=getattr(reg, "device_lease_keys", None),
    )
    report = runner.run_session(session_id, max_trials=max_trials)
    out = {
        "session_id": session_id,
        "final_state": report.final_session_state.value,
        "trials_processed": len(report.trials_processed),
        "halted_reason": report.halted_reason,
    }
    _emit(
        out,
        as_json,
        f"session {session_id} -> {out['final_state']} ({out['trials_processed']} trials processed)",
    )
    if report.halted_reason not in (None, "stop_requested"):
        raise typer.Exit(3)


@app.command()
@_guarded
def recover(
    session_id: str | None = typer.Argument(None, help="default: every interrupted session"),
    home: Path | None = HomeOpt,
    as_json: bool = JsonOpt,
) -> None:
    """Recover interrupted sessions: RUNNING trials -> ABORTED/interrupted_runner; fresh preflight required."""  # noqa: E501
    svc = EvalService(home)
    ids = [session_id] if session_id else [s.session_id for s in svc.find_interrupted()]
    out = {sid: [t.trial_id for t in svc.recover_interrupted(sid)] for sid in ids}
    _emit(
        out,
        as_json,
        "\n".join(f"{sid}: recovered {len(v)} trial(s)" for sid, v in out.items()) or "nothing to recover",
    )


@app.command()
@_guarded
def stop(
    session_id: str = typer.Argument(...),
    home: Path | None = HomeOpt,
    as_json: bool = JsonOpt,
) -> None:
    """Persist a software stop request (not an emergency stop). The runner polls it; no new trial starts."""
    first = EvalService(home).request_stop(session_id)
    _emit(
        {"session_id": session_id, "stop_requested": True, "first_request": first},
        as_json,
        f"stop requested for {session_id} (software request only; use the physical e-stop for emergencies)",
    )


@app.command("export-manifest")
@_guarded
def export_manifest(
    session_id: str = typer.Argument(...),
    out: Path | None = typer.Option(None, "--out", help="write manifest JSON here instead of stdout"),
    home: Path | None = HomeOpt,
    as_json: bool = JsonOpt,
) -> None:
    """Export the RunManifest (covers every planned trial)."""
    svc = EvalService(home)
    m = svc.export_manifest(session_id)
    from robotevalops.recording.manifest import write_manifest

    default_path = svc.run_dir(session_id) / "manifest.json"
    write_manifest(default_path, m)  # always keep runs/<id>/manifest.json current
    if out is not None:
        write_manifest(out, m)
        _emit(
            {"session_id": session_id, "path": str(out), "default_path": str(default_path)}
            | {"trials": len(m.trials)},  # noqa: E501
            as_json,
            f"wrote manifest for {len(m.trials)} trials to {out} and {default_path}",
        )
    else:
        sys.stdout.write(m.model_dump_json(indent=2) + chr(10))
