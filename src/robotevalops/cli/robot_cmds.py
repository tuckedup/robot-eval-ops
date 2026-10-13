"""`robotevalops robot ...` commands (Robotics-owned).

Hardware commands (teleop/record/rollout) refuse unless --hardware-mode, --ack-operator NAME and a
passing non-moving preflight are all present. --dry-run only prints the exact argument list and the
gate status; it never executes anything. calibrate/replay are NOT exposed (dry-run builders live in
the library only). Nothing here was verified against real hardware.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import typer

from robotevalops.adapters.hardware_so101 import SO101HardwareAdapter
from robotevalops.adapters.lerobot_dataset import inspect_dataset, split_episodes
from robotevalops.adapters.lerobot_wrapper import (
    CommandPlan,
    LeRobotWrapper,
    OperatorAcknowledgement,
    SO101Config,
    discover_lerobot,
    load_so101_config,
)
from robotevalops.adapters.registry import list_backends
from robotevalops.controllers.base import (
    configs_dir,
    load_conditions,
    load_controller_specs,
)
from robotevalops.errors import RobotEvalOpsError

app = typer.Typer(
    help="Robotics: adapters, simulation smoke, SO-101 hardware wrapper, datasets.", no_args_is_help=True
)

DEFAULT_CONFIG = typer.Option(None, "--config", help="SO-101 YAML (see configs/hardware/so101.example.yaml)")
JSON_OPT = typer.Option(False, "--json", help="Compact machine-readable JSON")


def _emit(obj: Any, as_json: bool) -> None:
    typer.echo(
        json.dumps(obj, sort_keys=True, default=str) if as_json else json.dumps(obj, indent=2, default=str)
    )


def _fail(msg: str, code: int = 1, as_json: bool = False) -> None:
    if as_json:
        typer.echo(json.dumps({"error": msg}))
    else:
        typer.echo(f"ERROR: {msg}", err=True)
    raise typer.Exit(code)


def _load_cfg(config: Path | None, as_json: bool) -> SO101Config:
    path = config or (configs_dir() / "hardware" / "so101.example.yaml")
    try:
        return load_so101_config(path)
    except (RobotEvalOpsError, OSError) as e:
        _fail(str(e), 2, as_json)
        raise


@app.command("adapters")
def adapters_cmd(as_json: bool = JSON_OPT) -> None:
    """List backends and whether each is available in this environment (no hardware access)."""
    _emit(list_backends(), as_json)


@app.command("sim-smoke")
def sim_smoke(
    trials: int = typer.Option(1, "--trials", min=1, max=20),
    controller: str = typer.Option("scripted_baseline_a", "--controller"),
    condition: str = typer.Option("nominal", "--condition"),
    seed: int = typer.Option(0, "--seed"),
    out: Path | None = typer.Option(
        None, "--out", help="Directory for video.mp4/trace.jsonl (default: temp)"
    ),
    render: bool = typer.Option(True, "--render/--no-render"),
    as_json: bool = JSON_OPT,
) -> None:
    """Run N PyBullet Panda trials (no database) and print the physics evidence JSON."""
    from robotevalops.adapters.registry import get_adapter, get_controller

    specs = {
        s.controller_id: s for s in load_controller_specs(configs_dir() / "controllers" / "sim_scripted.yaml")
    }
    conds = {c.name: c for c in load_conditions(configs_dir() / "conditions" / "sim_conditions.yaml")}
    if controller not in specs or condition not in conds:
        _fail(
            f"unknown controller/condition; controllers={sorted(specs)} conditions={sorted(conds)}",
            2,
            as_json,
        )
    try:
        adapter = get_adapter("pybullet_panda", None)
    except RobotEvalOpsError as e:
        _fail(str(e), 3, as_json)
        raise
    adapter.render = render  # type: ignore[attr-defined]
    base = out or Path(tempfile.mkdtemp(prefix="roe_sim_smoke_"))
    results = []
    try:
        for i in range(trials):
            adapter.reset(conds[condition], seed + i)
            ctl = get_controller(specs[controller], "pybullet_panda")
            res = adapter.run_episode(ctl, base / f"trial_{i}", 30.0, 2.0)
            results.append(
                {
                    "trial": i,
                    "seed": seed + i,
                    "termination_reason": res.termination_reason.value,
                    "task_success": res.task_success,
                    "duration_s": res.duration_s,
                    "error": res.error,
                    "recording": res.recording.model_dump(),
                    "evidence": res.evidence,
                }
            )
    finally:
        adapter.close()
    _emit(
        {"provenance": "simulation", "robot": "franka_panda", "out_dir": str(base), "trials": results},
        as_json,
    )
    if any(r["termination_reason"] in ("infra_failure", "recording_failure") for r in results):
        raise typer.Exit(1)


@app.command("hardware-check")
def hardware_check(config: Path | None = DEFAULT_CONFIG, as_json: bool = JSON_OPT) -> None:
    """Non-moving preflight of the SO-101 setup. Exit 1 if any check fails."""
    cfg = _load_cfg(config, as_json)
    pre = SO101HardwareAdapter(cfg).preflight()
    _emit(
        {
            "ok": pre.ok,
            "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in pre.checks],
            "note": "non-moving checks only; nothing was verified on real hardware by this repository",
        },
        as_json,
    )
    if not pre.ok:
        raise typer.Exit(1)


@app.command("lerobot-info")
def lerobot_info(as_json: bool = JSON_OPT) -> None:
    """Installed LeRobot version, entry points found, and authoritative source URLs."""
    _emit(discover_lerobot().as_dict(), as_json)


def _with_dry_run_names(wrapper: LeRobotWrapper) -> None:
    """For --dry-run: show a missing tool by its bare name instead of failing."""
    for tool, prefix in list(wrapper.info.executables.items()):
        if prefix is None:
            wrapper.info.executables[tool] = [tool]


def _hardware_flow(
    kind: str,
    config: Path | None,
    hardware_mode: bool,
    ack_operator: str | None,
    dry_run: bool,
    timeout: float,
    episodes: int | None,
    policy_path: str | None,
    as_json: bool,
) -> None:
    cfg = _load_cfg(config, as_json)
    adapter = SO101HardwareAdapter(
        cfg,
        hardware_mode=hardware_mode,
        acknowledgement=OperatorAcknowledgement(ack_operator, "cli-session") if ack_operator else None,
        session_id="cli-session",
    )
    wrapper = adapter.wrapper
    if dry_run:
        _with_dry_run_names(wrapper)
    try:
        plan: CommandPlan
        if kind == "teleop":
            plan = wrapper.build_teleoperate()
        elif kind == "record":
            plan = wrapper.build_record(num_episodes=episodes)
        else:
            plan = wrapper.build_rollout(policy_path=policy_path, num_episodes=episodes)
    except RobotEvalOpsError as e:
        _fail(str(e), 2, as_json)
        raise
    calib = wrapper.calibration_checks()
    if dry_run:
        gate_reason = adapter.gate().refusal()
        _emit(
            {
                "dry_run": True,
                "executed": False,
                "kind": plan.kind,
                "argv": plan.argv,
                "controller_type": plan.controller_type.value if plan.controller_type else None,
                "provenance": plan.provenance.value,
                "calibration_files": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in calib],
                "would_refuse": bool(gate_reason) or any(not c.ok for c in calib),
                "gate_note": gate_reason or "gate fields present; preflight still required at run time",
                "notes": plan.notes,
            },
            as_json,
        )
        return
    if not hardware_mode:
        _fail("refused: --hardware-mode is required to move hardware", 2, as_json)
    if not ack_operator or not ack_operator.strip():
        _fail("refused: --ack-operator NAME is required (per-session operator acknowledgement)", 2, as_json)
    pre = adapter.preflight()
    if not pre.ok:
        _fail(
            "refused: preflight failed: " + "; ".join(f"{c.name}: {c.detail}" for c in pre.failures()),
            2,
            as_json,
        )
    try:
        res = wrapper.run(plan, gate=adapter.gate(), timeout_s=timeout)
    except RobotEvalOpsError as e:
        _fail(str(e), 2, as_json)
        raise
    _emit(res.as_dict(), as_json)
    if not res.ok:
        raise typer.Exit(1)


@app.command("teleop")
def teleop(
    config: Path | None = DEFAULT_CONFIG,
    hardware_mode: bool = typer.Option(False, "--hardware-mode"),
    ack_operator: str | None = typer.Option(None, "--ack-operator"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    timeout: float = typer.Option(600.0, "--timeout"),
    as_json: bool = JSON_OPT,
) -> None:
    """Teleoperate follower with leader (lerobot-teleoperate). Needs hardware mode + ack + preflight."""
    _hardware_flow("teleop", config, hardware_mode, ack_operator, dry_run, timeout, None, None, as_json)


@app.command("record")
def record(
    config: Path | None = DEFAULT_CONFIG,
    hardware_mode: bool = typer.Option(False, "--hardware-mode"),
    ack_operator: str | None = typer.Option(None, "--ack-operator"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    timeout: float = typer.Option(3600.0, "--timeout"),
    episodes: int | None = typer.Option(None, "--episodes", min=1),
    as_json: bool = JSON_OPT,
) -> None:
    """Record teleoperated episodes (lerobot-record). Needs hardware mode + ack + preflight."""
    _hardware_flow("record", config, hardware_mode, ack_operator, dry_run, timeout, episodes, None, as_json)


@app.command("rollout")
def rollout(
    config: Path | None = DEFAULT_CONFIG,
    hardware_mode: bool = typer.Option(False, "--hardware-mode"),
    ack_operator: str | None = typer.Option(None, "--ack-operator"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    timeout: float = typer.Option(3600.0, "--timeout"),
    episodes: int | None = typer.Option(None, "--episodes", min=1),
    policy_path: str | None = typer.Option(None, "--policy-path"),
    as_json: bool = JSON_OPT,
) -> None:
    """Supervised learned-policy rollout (lerobot-record --policy.path); needs mode + ack + preflight."""
    _hardware_flow(
        "rollout", config, hardware_mode, ack_operator, dry_run, timeout, episodes, policy_path, as_json
    )


@app.command("import-dataset")
def import_dataset(
    path: Path | None = typer.Option(None, "--path", help="LeRobot-compatible dataset directory"),
    eval_fraction: float = typer.Option(0.2, "--eval-fraction"),
    seed: int = typer.Option(0, "--split-seed"),
    as_json: bool = JSON_OPT,
) -> None:
    """Inspect a LeRobot-format dataset read-only and print an episode-level train/eval split."""
    if path is None:
        _emit(
            {
                "dataset": None,
                "message": "no dataset provided (--path); none exists in this repository; nothing imported.",
            },
            as_json,
        )
        return
    try:
        summary = inspect_dataset(path)
        n = summary.get("total_episodes")
        split = None
        if isinstance(n, int) and n >= 2:
            split = split_episodes(list(range(n)), eval_fraction, seed)
    except RobotEvalOpsError as e:
        _fail(str(e), 2, as_json)
        raise
    _emit({"dataset": summary, "episode_split": split, "split_unit": "whole episodes"}, as_json)
