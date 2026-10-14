# ruff: noqa: E501
"""Pre-specified physics stress study: plan -> pilot -> freeze -> evaluate -> report.

Rules enforced in code (not just documented):
  * the pilot and the held-out evaluation use different base seeds and the derived seed sets must not overlap;
  * the evaluation refuses to run unless the protocol (protocol + conditions + controllers files) matches the
    hash recorded when it was frozen after a clean pilot;
  * every attempted trial is reported; failures are categorised from recorded simulator evidence only and link
    to the trial's video and trace; nothing is dropped, re-seeded or re-labelled.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from robotevalops.adapters.sim_pybullet import STRESS_BOUNDS, STRESS_NOMINAL
from robotevalops.controllers.base import configs_dir
from robotevalops.core.service import EvalService
from robotevalops.errors import RobotEvalOpsError
from robotevalops.metrics.stats import wilson_interval
from robotevalops.schemas import (
    ArtifactRole,
    EvalConfig,
    Provenance,
    TaskOutcome,
    TrialRecord,
    TrialState,
    is_autonomous_success,
)
from robotevalops.util import derive_seed, git_commit, sha256_bytes, utcnow

FAILURE_CATEGORIES = (
    "grasp_failed",
    "lift_failed",
    "dropped_in_transit",
    "placement_outside_target",
    "release_failed",
    "dwell_not_held",
    "infra_failure",
    "unverified_recording",
)
DROPPED_DISTANCE_M = 0.10


def load_protocol(path: str | Path) -> dict[str, Any]:
    if not Path(path).is_file():
        raise RobotEvalOpsError(f"protocol file not found: {path} (pass --protocol <file>)")
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "protocol_id" not in data:
        raise RobotEvalOpsError(f"{path}: not a stress protocol")
    return data


def _ref_files(protocol_path: Path, proto: dict[str, Any]) -> dict[str, Path]:
    base = configs_dir()
    return {
        "protocol": protocol_path,
        "conditions": base / proto["conditions_from"],
        "controllers": base / proto["controllers_from"],
    }


def protocol_digest(protocol_path: str | Path) -> dict[str, Any]:
    p = Path(protocol_path)
    proto = load_protocol(p)
    files = {k: sha256_bytes(f.read_bytes()) for k, f in _ref_files(p, proto).items()}
    return {
        "protocol_id": proto["protocol_id"],
        "files": files,
        "combined_sha256": sha256_bytes(json.dumps(files, sort_keys=True).encode()),
    }


def frozen_path(protocol_path: str | Path) -> Path:
    p = Path(protocol_path)
    return p.with_name(p.stem + ".frozen.json")


def seed_sets(proto: dict[str, Any]) -> dict[str, set[int]]:
    names = [n for fam in proto["families"].values() for n in fam]
    out = {}
    for stage in ("pilot", "evaluation"):
        s = proto[stage]
        out[stage] = {
            derive_seed(s["base_seed"], n, i) for n in names for i in range(s["trials_per_condition"])
        }
    return out


def check_seeds_disjoint(proto: dict[str, Any]) -> None:
    s = seed_sets(proto)
    common = s["pilot"] & s["evaluation"]
    if proto["pilot"]["base_seed"] == proto["evaluation"]["base_seed"] or common:
        raise RobotEvalOpsError(f"pilot and evaluation seeds overlap ({len(common)} shared); refusing to run")


def stage_configs(protocol_path: str | Path, stage: str) -> list[tuple[str, EvalConfig]]:
    p = Path(protocol_path)
    proto = load_protocol(p)
    check_seeds_disjoint(proto)
    conds = {c.name: c for c in load_eval_config_conditions(proto)}
    ctrls = load_eval_controllers(proto)
    from robotevalops.schemas import TaskSpec

    out = []
    for fam, names in proto["families"].items():
        out.append(
            (
                fam,
                EvalConfig(
                    name=f"{proto['protocol_id']}-{stage}-{fam}",
                    task=TaskSpec(**proto["task"]),
                    provenance=Provenance(proto["provenance"]),
                    backend=proto["backend"],
                    controllers=ctrls,
                    conditions=[conds[n] for n in names],
                    trials_per_condition=proto[stage]["trials_per_condition"],
                    base_seed=proto[stage]["base_seed"],
                ),
            )
        )
    return out


def load_eval_config_conditions(proto: dict[str, Any]) -> list[Any]:
    from robotevalops.controllers.base import load_conditions

    return load_conditions(configs_dir() / proto["conditions_from"])


def load_eval_controllers(proto: dict[str, Any]) -> list[Any]:
    from robotevalops.controllers.base import load_controller_specs

    return load_controller_specs(configs_dir() / proto["controllers_from"])


def plan_stage(home: str | Path, protocol_path: str | Path, stage: str) -> list[str]:
    svc = EvalService(home)
    ids = []
    for _fam, cfg in stage_configs(protocol_path, stage):
        s = svc.create_session(
            cfg.name, cfg.provenance, cfg.backend, eval_config=cfg, purpose=f"stress-study {stage}"
        )
        svc.plan_trials(s.session_id, cfg)
        ids.append(s.session_id)
    return ids


def run_sessions(home: str | Path, session_ids: list[str], workers: int = 6) -> dict[str, int]:
    """Run each session in its own `robotevalops session run` process (the real CLI path: QA + manifest hooks).
    Returns session_id -> exit code."""
    pending = list(session_ids)
    running: dict[str, subprocess.Popen[bytes]] = {}
    codes: dict[str, int] = {}
    while pending or running:
        while pending and len(running) < workers:
            sid = pending.pop(0)
            running[sid] = subprocess.Popen(
                [sys.executable, "-m", "robotevalops.cli.main", "session", "run", sid, "--home", str(home)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        for sid, proc in list(running.items()):
            rc = proc.poll()
            if rc is not None:
                codes[sid] = rc
                del running[sid]
        if running:
            import time

            time.sleep(0.5)
    return codes


# ----------------------------------------------------------------------------- evidence


def categorize(t: TrialRecord) -> str | None:
    """None for a verified autonomous success; otherwise one failure category from recorded evidence."""
    if is_autonomous_success(t):
        return None
    if t.state != TrialState.COMPLETED:
        return "infra_failure"
    if t.task_outcome == TaskOutcome.SUCCESS:
        return "unverified_recording"
    ev = t.evidence
    if t.task_outcome != TaskOutcome.FAILURE:
        return "infra_failure"
    if not ev.get("bilateral_contact_ok"):
        return "grasp_failed"
    if not ev.get("lift_ok"):
        return "lift_failed"
    tc = ev.get("target_center_xy") or [0.5, 0.2]
    fp = ev.get("block_final_pos") or [math.nan, math.nan]
    dist = math.hypot(fp[0] - tc[0], fp[1] - tc[1])
    if not ev.get("all_corners_inside"):
        return "dropped_in_transit" if dist >= DROPPED_DISTANCE_M else "placement_outside_target"
    if not ev.get("released"):
        return "release_failed"
    return "dwell_not_held"


def _level(trial: TrialRecord, factor: str) -> float:
    applied = (trial.evidence.get("applied_condition") or {}).get("physics_stress") or {}
    return float(applied.get(factor, STRESS_NOMINAL[factor]))


@dataclass
class Cell:
    family: str
    condition: str
    controller_id: str
    factor: str | None
    level: float | None
    n_attempted: int
    n_success: int
    rate: float | None
    ci_low: float | None
    ci_high: float | None
    categories: dict[str, int]


def analyze_stage(home: str | Path, protocol_path: str | Path, stage: str = "evaluation") -> dict[str, Any]:
    proto = load_protocol(protocol_path)
    svc = EvalService(home)
    prefix = f"{proto['protocol_id']}-{stage}-"
    sessions = [s for s in svc.list_sessions() if s.name.startswith(prefix)]
    if not sessions:
        raise RobotEvalOpsError(f"no sessions named {prefix}* in {home}")
    trials: list[TrialRecord] = []
    fam_of_session = {s.session_id: s.name[len(prefix) :] for s in sessions}
    for s in sessions:
        trials += svc.list_trials(s.session_id)
    factor_of = proto["factor_of_family"]
    cells: list[Cell] = []
    groups: dict[tuple[str, str, str], list[TrialRecord]] = defaultdict(list)
    for t in trials:
        groups[(fam_of_session[t.session_id], t.condition_name, t.controller_id)].append(t)
    for (fam, cond, ctrl), ts in sorted(groups.items()):
        att = [t for t in ts if t.is_attempted]
        succ = sum(is_autonomous_success(t) for t in att)
        ci = wilson_interval(succ, len(att))
        factor = factor_of.get(fam)
        level = _level(ts[0], factor) if factor else None
        cats = Counter(c for t in att if (c := categorize(t)))
        cells.append(
            Cell(
                fam,
                cond,
                ctrl,
                factor,
                level,
                len(att),
                succ,
                succ / len(att) if att else None,
                ci[0] if ci else None,
                ci[1] if ci else None,
                dict(cats),
            )
        )
    envelope = _envelope(cells, proto)
    failures = []
    for t in sorted(trials, key=lambda x: (x.condition_name, x.controller_id, x.trial_index)):
        cat = categorize(t)
        if cat is None:
            continue
        arts = {a.role: a.relpath for a in t.artifacts}
        ev = t.evidence
        failures.append(
            {
                "category": cat,
                "family": fam_of_session[t.session_id],
                "condition": t.condition_name,
                "controller_id": t.controller_id,
                "trial_index": t.trial_index,
                "seed": t.seed,
                "trial_id": t.trial_id,
                "session_id": t.session_id,
                "failed_criteria": ev.get("failed_criteria"),
                "final_offset_from_target_m": _offset(ev),
                "max_contact_normal_force_n": ev.get("max_contact_normal_force_n"),
                "video": f"runs/{t.session_id}/{arts[ArtifactRole.VIDEO]}"
                if ArtifactRole.VIDEO in arts
                else None,
                "trace": f"runs/{t.session_id}/{arts[ArtifactRole.TRACE]}"
                if ArtifactRole.TRACE in arts
                else None,
            }
        )
    attempted = [t for t in trials if t.is_attempted]
    return {
        "protocol_id": proto["protocol_id"],
        "stage": stage,
        "home": str(home),
        "generated_at": utcnow().isoformat(),
        "denominators": {
            "planned": len(trials),
            "attempted": len(attempted),
            "verified_successes": sum(is_autonomous_success(t) for t in trials),
            "task_failures": sum(t.task_outcome == TaskOutcome.FAILURE for t in trials),
            "infra_failures": sum(t.state == TrialState.FAILED for t in trials),
            "unverified_recordings": sum(
                t.task_outcome == TaskOutcome.SUCCESS and not is_autonomous_success(t) for t in trials
            ),
        },
        "failure_categories": dict(Counter(f["category"] for f in failures)),
        "cells": [c.__dict__ for c in cells],
        "envelope": envelope,
        "failures": failures,
        "sessions": [s.session_id for s in sessions],
    }


def _offset(ev: dict[str, Any]) -> float | None:
    tc, fp = ev.get("target_center_xy"), ev.get("block_final_pos")
    return math.hypot(fp[0] - tc[0], fp[1] - tc[1]) if tc and fp else None


def _envelope(cells: list[Cell], proto: dict[str, Any]) -> dict[str, Any]:
    """Per controller and single-factor family: success at each level in severity order, first level < 100%, first < 50%."""
    out: dict[str, Any] = {}
    ref = {c.controller_id: c for c in cells if c.family == "reference"}
    for ctrl in sorted({c.controller_id for c in cells}):
        fams = {}
        for fam, names in proto["families"].items():
            if fam in ("reference", "joint"):
                continue
            rows = []
            nominal = proto["nominal_levels"][proto["factor_of_family"][fam]]
            if ctrl in ref:
                rows.append(
                    {
                        "condition": "stress_nominal",
                        "level": nominal,
                        "rate": ref[ctrl].rate,
                        "n": ref[ctrl].n_attempted,
                    }
                )
            for n in names:
                c = next((x for x in cells if x.controller_id == ctrl and x.condition == n), None)
                if c:
                    rows.append(
                        {
                            "condition": n,
                            "level": c.level,
                            "rate": c.rate,
                            "n": c.n_attempted,
                            "ci": [c.ci_low, c.ci_high],
                            "categories": c.categories,
                        }
                    )
            first_lt100 = next(
                (r["condition"] for r in rows if r["rate"] is not None and r["rate"] < 1.0), None
            )
            first_lt50 = next(
                (r["condition"] for r in rows if r["rate"] is not None and r["rate"] < 0.5), None
            )
            fams[fam] = {
                "levels": rows,
                "first_level_below_100pct": first_lt100,
                "first_level_below_50pct": first_lt50,
            }
        out[ctrl] = fams
    return out


def render_report(res: dict[str, Any], proto: dict[str, Any]) -> str:
    d = res["denominators"]
    L = [f"# Physics stress study `{res['protocol_id']}` ({res['stage']})\n"]
    L.append(
        "> **SIMULATION ONLY: Panda arm, PyBullet, scripted (not learned) controllers. No claim about a real robot or a learned policy.**\n"
    )
    L.append(
        f"Attempted **{d['attempted']}** of {d['planned']} planned trials: {d['verified_successes']} verified successes, "
        f"{d['task_failures']} task failures, {d['infra_failures']} infra failures, {d['unverified_recordings']} unverified recordings. "
        "Every attempted trial is in the denominator; nothing was dropped or re-run.\n"
    )
    L.append("## Failure categories (from recorded simulator evidence)\n")
    for k, v in sorted(res["failure_categories"].items(), key=lambda kv: -kv[1]):
        L.append(f"- `{k}`: {v}")
    L.append("\n## Failure envelope by controller and factor\n")
    L.append(
        "Success rate per level (k/n), mildest to most severe; the level column is the applied physical value.\n"
    )
    for ctrl, fams in res["envelope"].items():
        L.append(f"### {ctrl}\n")
        L.append("| family | levels (value: success) | first < 100% | first < 50% |")
        L.append("|---|---|---|---|")
        for fam, e in fams.items():
            lv = "; ".join(
                f"{r['level']:g}: {round(r['rate'] * r['n'])}/{r['n']}"
                for r in e["levels"]
                if r["rate"] is not None
            )
            L.append(
                f"| {fam} | {lv} | {e['first_level_below_100pct'] or '-'} | {e['first_level_below_50pct'] or '-'} |"
            )
        L.append("")
    joint = [c for c in res["cells"] if c["family"] == "joint"]
    if joint:
        L.append("## Combined stress\n")
        for c in joint:
            L.append(
                f"- {c['condition']} / {c['controller_id']}: {c['n_success']}/{c['n_attempted']}  categories {c['categories']}"
            )
    L.append("\n## Failures with evidence links\n")
    L.append(
        "| category | condition | controller | trial | seed | offset from target (m) | max contact force (N) | video | trace |"
    )
    L.append("|---|---|---|---|---:|---:|---:|---|---|")
    for f in res["failures"]:
        off = f"{f['final_offset_from_target_m']:.3f}" if f["final_offset_from_target_m"] is not None else "-"
        frc = f"{f['max_contact_normal_force_n']:.1f}" if f["max_contact_normal_force_n"] is not None else "-"
        L.append(
            f"| {f['category']} | {f['condition']} | {f['controller_id']} | {f['trial_index']} | {f['seed']} | {off} | {frc} | `{f['video']}` | `{f['trace']}` |"
        )
    L.append("\n## Limits\n")
    L += [f"- {x}" for x in proto["interpretation_limits"]]
    L.append("\n## Pre-specified hypotheses (frozen before evaluation)\n")
    L += [f"- {h}" for h in proto["hypotheses"]]
    return "\n".join(L) + "\n"


def pilot_findings(home: str | Path, protocol_path: str | Path) -> dict[str, Any]:
    """Feasibility checks on the pilot. Task failures are fine; crashes, infra failures, clamped parameters and
    unreadable evidence are not."""
    proto = load_protocol(protocol_path)
    svc = EvalService(home)
    prefix = f"{proto['protocol_id']}-pilot-"
    trials = [
        t for s in svc.list_sessions() if s.name.startswith(prefix) for t in svc.list_trials(s.session_id)
    ]
    conds = {c.name: c for c in load_eval_config_conditions(proto)}
    problems = []
    for t in trials:
        if t.state != TrialState.COMPLETED:
            problems.append(
                f"{t.condition_name}/{t.controller_id}: state {t.state.value} ({t.termination_reason.value})"
            )
            continue
        applied = (t.evidence.get("applied_condition") or {}).get("physics_stress")
        if applied is None:
            problems.append(f"{t.condition_name}: no applied physics_stress evidence")
            continue
        for k, v in conds[t.condition_name].params.items():
            lo, hi = STRESS_BOUNDS[k]
            if not (lo <= float(v) <= hi):
                problems.append(f"{t.condition_name}: {k}={v} outside bounds {lo}..{hi}")
            if abs(float(applied[k]) - float(v)) > 1e-9:
                problems.append(f"{t.condition_name}: {k} requested {v} applied {applied[k]} (clamped)")
    return {
        "trials": len(trials),
        "completed": sum(t.state == TrialState.COMPLETED for t in trials),
        "task_failures": sum(t.task_outcome == TaskOutcome.FAILURE for t in trials),
        "problems": problems,
        "clean": bool(trials) and not problems,
    }


def freeze(protocol_path: str | Path, pilot_home: str | Path) -> dict[str, Any]:
    p = Path(protocol_path)
    if frozen_path(p).exists():
        raise RobotEvalOpsError(f"{frozen_path(p).name} already exists: a frozen protocol is never re-frozen")
    pf = pilot_findings(pilot_home, p)
    if not pf["clean"]:
        raise RobotEvalOpsError(f"pilot is not clean; cannot freeze: {pf['problems'][:5]}")
    dig = protocol_digest(p)
    rec = {
        **dig,
        "frozen_at": utcnow().isoformat(),
        "git_commit": git_commit(),
        "pilot": {"home": str(pilot_home), **pf},
        "seed_sets_disjoint": True,
        "note": "the evaluation stage refuses to run unless the three files below still match these hashes",
    }
    frozen_path(p).write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    return rec


def require_frozen(protocol_path: str | Path) -> dict[str, Any]:
    p = Path(protocol_path)
    load_protocol(p)  # clear error if the protocol file itself is missing
    fp = frozen_path(p)
    if not fp.is_file():
        raise RobotEvalOpsError("protocol is not frozen: run the pilot, then `robotevalops study freeze`")
    rec = json.loads(fp.read_text(encoding="utf-8"))
    now = protocol_digest(p)
    if now["files"] != rec["files"]:
        changed = [k for k in now["files"] if now["files"][k] != rec["files"].get(k)]
        raise RobotEvalOpsError(
            f"protocol changed after freezing ({changed}); a change means a new protocol_id"
        )
    return rec


def plot_envelope(res: dict[str, Any], out: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {"scripted_baseline_a": "#0072B2", "scripted_baseline_b": "#D55E00"}
    styles = {"scripted_baseline_a": ("-", "o"), "scripted_baseline_b": ("--", "s")}
    fams = [f for f in next(iter(res["envelope"].values()))]
    cols = 4
    rows = math.ceil(len(fams) / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(4.0 * cols, 3.0 * rows), sharey=True, squeeze=False)
    for ax in axes.ravel():
        ax.set_visible(False)
    for ax, fam in zip(axes.ravel(), fams, strict=False):
        ax.set_visible(True)
        for ctrl, e in res["envelope"].items():
            lv = [r for r in e[fam]["levels"] if r["rate"] is not None]
            xs = list(range(len(lv)))
            ls, mk = styles.get(ctrl, ("-", "o"))
            ax.plot(
                xs,
                [r["rate"] for r in lv],
                ls=ls,
                marker=mk,
                color=colors.get(ctrl, "#444"),
                lw=1.8,
                ms=6,
                mec="white",
                label=ctrl.replace("scripted_baseline_", "controller "),
            )
        ax.set_xticks(xs)
        ax.set_xticklabels([f"{r['level']:g}" for r in lv], rotation=0, fontsize=8)
        ax.set_title(fam, fontsize=10)
        ax.set_ylim(-0.05, 1.05)
        ax.grid(alpha=0.25, lw=0.5)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0][0].set_ylabel("verified success rate")
    axes[0][0].legend(frameon=False, fontsize=8, loc="lower left")
    fig.suptitle(
        f"Failure envelope, {res['protocol_id']} ({res['stage']}), attempted n={res['denominators']['attempted']}; x = applied factor value, mildest first",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)
    return out
