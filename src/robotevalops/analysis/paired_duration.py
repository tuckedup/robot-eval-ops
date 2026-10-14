# ruff: noqa: E501
"""Paired duration / trade-off analysis of two controllers over an EXISTING session (read-only).

Design facts this analysis refuses to hide:
  * Trials are PAIRED (same session, condition, trial_index, seed): the unit of comparison is the pair.
  * Many pairs are not independent. Lighting/background/occlusion change rendered pixels that a state-based
    scripted controller never reads, and the nominal start is fixed, so those trials replay the SAME physical
    scenario. They are collapsed into one *scenario* (identical block start pose) before any inference.
    Inference units are therefore distinct start scenarios, not trial counts.
  * Durations are SIMULATED seconds of a Panda arm in PyBullet. They are not robot throughput or reset time,
    and say nothing about a real SO-101.
  * The start scenarios are a narrow, bounded perturbation (+-4 cm) around one nominal pose; an interval
    describes that distribution only.
The raw per-trial means (trial-weighted) are reported next to the scenario-weighted ones so the effect of
pseudo-replication is visible instead of silent.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from robotevalops.schemas import ArtifactRole, TrialRecord, is_autonomous_success

START_ROUND = 4  # decimals (0.1 mm) of the block start position that define "the same scenario"
BOOTSTRAP_SAMPLES = 20_000
BOOTSTRAP_SEED = 20261014  # fixed: the interval is reproducible


@dataclass
class TrialRow:
    trial_id: str
    controller_id: str
    condition: str
    trial_index: int
    seed: int
    scenario: str
    duration_s: float
    metrics: dict[str, float]
    trace_relpath: str | None


@dataclass
class Interval:
    mean: float
    ci_low: float
    ci_high: float
    method: str = "percentile bootstrap over scenarios (20000 resamples, fixed seed), 95%"


@dataclass
class PairedStat:
    name: str
    unit: str
    n_scenarios: int
    mean_a: float
    mean_b: float
    mean_diff_a_minus_b: float
    diff_interval: Interval
    relative_change_b_vs_a: float | None
    rel_interval: Interval | None
    n_a_greater: int
    n_b_greater: int
    n_ties: int
    sign_test_p_two_sided: float | None
    per_scenario_diffs: list[float] = field(default_factory=list)


def _scenario_key(evidence: dict[str, Any]) -> str:
    pos = evidence.get("block_start_pos")
    if not (isinstance(pos, list) and len(pos) >= 2):
        raise ValueError("trial evidence has no block_start_pos; cannot identify the physical scenario")
    return f"{round(float(pos[0]), START_ROUND):.4f},{round(float(pos[1]), START_ROUND):.4f}"


def sign_test_p(n_pos: int, n_neg: int) -> float | None:
    n = n_pos + n_neg
    if n == 0:
        return None
    tail = sum(math.comb(n, i) for i in range(min(n_pos, n_neg) + 1))
    return min(1.0, 2.0 * tail / 2**n)


def paired_stat(name: str, unit: str, a: Sequence[float], b: Sequence[float]) -> PairedStat:
    """a[i], b[i] are the two controllers' values on scenario i (already scenario-averaged)."""
    A, B = np.asarray(a, float), np.asarray(b, float)
    if len(A) != len(B) or len(A) == 0:
        raise ValueError("paired_stat needs equal, non-empty scenario vectors")
    d = A - B
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    n = len(d)
    idx = rng.integers(0, n, size=(BOOTSTRAP_SAMPLES, n))
    mean_d = float(d.mean())
    lo, hi = np.percentile(d[idx].mean(axis=1), [2.5, 97.5])
    rel: float | None = None
    rel_int: Interval | None = None
    if A.mean() != 0:
        rel = float((B.mean() - A.mean()) / A.mean())
        ra = A[idx].mean(axis=1)
        rb = B[idx].mean(axis=1)
        ok = ra != 0
        draws = (rb[ok] - ra[ok]) / ra[ok]
        rlo, rhi = np.percentile(draws, [2.5, 97.5])
        rel_int = Interval(rel, float(rlo), float(rhi))
    pos, neg = int((d > 0).sum()), int((d < 0).sum())
    return PairedStat(
        name=name,
        unit=unit,
        n_scenarios=n,
        mean_a=float(A.mean()),
        mean_b=float(B.mean()),
        mean_diff_a_minus_b=mean_d,
        diff_interval=Interval(mean_d, float(lo), float(hi)),
        relative_change_b_vs_a=rel,
        rel_interval=rel_int,
        n_a_greater=pos,
        n_b_greater=neg,
        n_ties=int((d == 0).sum()),
        sign_test_p_two_sided=sign_test_p(pos, neg),
        per_scenario_diffs=[float(x) for x in d],
    )


def _metrics(ev: dict[str, Any]) -> dict[str, float]:
    tc = ev.get("target_center_xy") or [0.0, 0.0]
    fx, fy = (ev.get("block_final_pos") or [math.nan, math.nan, math.nan])[:2]
    out = {
        "max_contact_normal_force_n": float(ev.get("max_contact_normal_force_n", math.nan)),
        "final_distance_to_target_center_m": math.hypot(float(fx) - tc[0], float(fy) - tc[1]),
        "block_final_speed_mps": float(ev.get("block_final_speed_mps", math.nan)),
        "max_block_height_m": float(ev.get("max_block_height_m", math.nan)),
        "in_target_fraction": float(ev.get("in_target_fraction", math.nan)),
    }
    return out


def rows_from_trials(trials: Sequence[TrialRecord]) -> list[TrialRow]:
    rows = []
    for t in trials:
        if not is_autonomous_success(t):
            continue  # only verified successes carry comparable durations
        if t.duration_s is None:
            continue
        trace = next((a.relpath for a in t.artifacts if a.role == ArtifactRole.TRACE), None)
        rows.append(
            TrialRow(
                t.trial_id,
                t.controller_id,
                t.condition_name,
                t.trial_index,
                t.seed,
                _scenario_key(t.evidence),
                float(t.duration_s),
                _metrics(t.evidence),
                trace,
            )
        )
    return rows


def _scenario_means(rows: Sequence[TrialRow], controller: str, field_: str | None) -> dict[str, float]:
    by: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r.controller_id == controller:
            by[r.scenario].append(r.duration_s if field_ is None else r.metrics[field_])
    return {k: statistics.fmean(v) for k, v in by.items()}


def trace_phases(trace_path: Path) -> dict[str, float] | None:
    """Controller-command phase times from a recorded trace: close_cmd (first finger_target < 0.01 m),
    open_cmd (first finger_target > 0.03 m after closing), end. Values are copied from the recorded
    actions; nothing is imputed. None if the trace is unreadable or lacks the events."""
    try:
        lines = trace_path.read_text(encoding="utf-8").splitlines()
        header = json.loads(lines[0])
        ai = header["action_names"].index("finger_target_m")
        rows = [json.loads(x) for x in lines[1:] if x.strip()]
    except (OSError, ValueError, KeyError, IndexError):
        return None
    close_t = open_t = None
    for r in rows:
        f = r["action"][ai]
        if close_t is None and f < 0.01:
            close_t = r["t"]
        elif close_t is not None and open_t is None and f > 0.03:
            open_t = r["t"]
    if close_t is None or open_t is None:
        return None
    end = rows[-1]["t"]
    return {
        "approach_s": close_t,
        "carry_s": open_t - close_t,
        "release_and_dwell_s": end - open_t,
        "total_s": end,
    }


@dataclass
class Analysis:
    controller_a: str
    controller_b: str
    session_ids: list[str]
    n_trial_pairs: int
    n_scenarios: int
    n_replayed_scenarios: int
    scenario_table: list[dict[str, Any]]
    condition_table: list[dict[str, Any]]
    duration: PairedStat
    trial_weighted: dict[str, float]
    tradeoffs: list[PairedStat]
    phases: dict[str, dict[str, float]]
    controller_params: dict[str, dict[str, Any]]
    caveats: list[str]
    unpaired: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CAVEATS = [
    "Durations are SIMULATED seconds (PyBullet Panda, 20 Hz control). They are not robot throughput, "
    "reset time, or any real-world measurement; the arm is a Panda, not an SO-101.",
    "Deterministic replay: lighting/background/occlusion only change rendered pixels that these state-based "
    "scripted controllers never read, and the nominal start is fixed. Those trials replay one physical "
    "scenario, so they are collapsed before inference. Trial counts overstate the evidence.",
    "Inference units are distinct start scenarios (a bounded +-4 cm perturbation around one nominal pose). "
    "Intervals describe that start distribution in this simulator only; they do not generalise to other "
    "objects, friction, masses, delays or a real arm.",
    "Both controllers succeeded on every trial, so duration is the only discriminating outcome here. A faster "
    "controller is not shown to be better: see the trade-off table (contact force, placement accuracy, "
    "final block speed) and the failure study for what the speed costs.",
    "Both durations include a fixed 2.0 s placement dwell, so the relative saving in ACTIVE time is larger "
    "than the relative saving in total time.",
]


def analyze(
    trials: Sequence[TrialRecord],
    controller_a: str,
    controller_b: str,
    controller_params: dict[str, dict[str, Any]] | None = None,
    run_root: Path | None = None,
) -> Analysis:
    ts = [t for t in trials if t.controller_id in (controller_a, controller_b)]
    rows = rows_from_trials(ts)
    if not rows:
        raise ValueError("no verified autonomous successes for these controllers; nothing to analyse")
    # --- pairing: same session + condition + trial_index, equal seed
    by_key: dict[tuple[str, str, int], dict[str, TrialRecord]] = defaultdict(dict)
    for t in ts:
        by_key[(t.session_id, t.condition_name, t.trial_index)][t.controller_id] = t
    ok_ids = {r.trial_id for r in rows}
    unpaired: list[str] = []
    paired_ids: set[str] = set()
    for key, d in sorted(by_key.items()):
        if set(d) != {controller_a, controller_b}:
            unpaired.append(f"{key}: missing partner")
        elif d[controller_a].seed != d[controller_b].seed:
            unpaired.append(f"{key}: seed mismatch")
        elif d[controller_a].trial_id not in ok_ids or d[controller_b].trial_id not in ok_ids:
            unpaired.append(f"{key}: not a verified autonomous success for both")
        else:
            paired_ids.update(t.trial_id for t in d.values())
    prow = [r for r in rows if r.trial_id in paired_ids]
    if not prow:
        raise ValueError("no complete pairs")
    n_pairs = len(prow) // 2
    ma, mb = _scenario_means(prow, controller_a, None), _scenario_means(prow, controller_b, None)
    scen = sorted(set(ma) & set(mb))
    if set(ma) != set(mb):
        unpaired.append(f"scenarios present for only one controller: {sorted(set(ma) ^ set(mb))}")
    dur = paired_stat("duration", "s (simulated)", [ma[s] for s in scen], [mb[s] for s in scen])
    # replay evidence: within a scenario and controller, are trials bit-identical?
    spread: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in prow:
        spread[(r.controller_id, r.scenario)].append(r.duration_s)
    replayed = sorted({s for (c, s), v in spread.items() if len(v) > 1})
    scenario_table = []
    for s in scen:
        counts = {c: len(spread[(c, s)]) for c in (controller_a, controller_b)}
        conds = sorted({r.condition for r in prow if r.scenario == s})
        scenario_table.append(
            {
                "scenario_block_start_xy": s,
                "trials_per_controller": counts[controller_a],
                "conditions": conds,
                "duration_a_s": ma[s],
                "duration_b_s": mb[s],
                "diff_a_minus_b_s": ma[s] - mb[s],
                "replays_identical": all(
                    max(spread[(c, s)]) - min(spread[(c, s)]) < 1e-9 for c in (controller_a, controller_b)
                ),
            }
        )
    cond_table = []
    for cond in sorted({r.condition for r in prow}):
        a = [r.duration_s for r in prow if r.condition == cond and r.controller_id == controller_a]
        b = [r.duration_s for r in prow if r.condition == cond and r.controller_id == controller_b]
        cond_table.append(
            {
                "condition": cond,
                "n_pairs": len(a),
                "distinct_scenarios": len({r.scenario for r in prow if r.condition == cond}),
                "mean_a_s": statistics.fmean(a),
                "mean_b_s": statistics.fmean(b),
                "mean_diff_a_minus_b_s": statistics.fmean(a) - statistics.fmean(b),
                "sd_a_s": statistics.pstdev(a),
                "sd_b_s": statistics.pstdev(b),
            }
        )
    all_a = [r.duration_s for r in prow if r.controller_id == controller_a]
    all_b = [r.duration_s for r in prow if r.controller_id == controller_b]
    trial_weighted = {
        "n_trial_pairs": float(n_pairs),
        "mean_a_s": statistics.fmean(all_a),
        "mean_b_s": statistics.fmean(all_b),
        "relative_change_b_vs_a": (statistics.fmean(all_b) - statistics.fmean(all_a))
        / statistics.fmean(all_a),
    }
    tradeoffs = []
    labels = {
        "max_contact_normal_force_n": "N",
        "final_distance_to_target_center_m": "m",
        "block_final_speed_mps": "m/s",
        "max_block_height_m": "m",
    }
    for m, unit in labels.items():
        sa, sb = _scenario_means(prow, controller_a, m), _scenario_means(prow, controller_b, m)
        tradeoffs.append(paired_stat(m, unit, [sa[s] for s in scen], [sb[s] for s in scen]))
    phases: dict[str, dict[str, float]] = {}
    if run_root is not None:
        for c in (controller_a, controller_b):
            sample = next((r for r in prow if r.controller_id == c and r.scenario == scen[0]), None)
            tr = next((t for t in ts if sample and t.trial_id == sample.trial_id), None)
            if sample and sample.trace_relpath and tr:
                ph = trace_phases(run_root / tr.session_id / sample.trace_relpath)
                if ph:
                    phases[c] = ph
    return Analysis(
        controller_a=controller_a,
        controller_b=controller_b,
        session_ids=sorted({t.session_id for t in ts}),
        n_trial_pairs=n_pairs,
        n_scenarios=len(scen),
        n_replayed_scenarios=len(replayed),
        scenario_table=scenario_table,
        condition_table=cond_table,
        duration=dur,
        trial_weighted=trial_weighted,
        tradeoffs=tradeoffs,
        phases=phases,
        controller_params=controller_params or {},
        caveats=list(CAVEATS),
        unpaired=unpaired,
    )


def render_markdown(a: Analysis) -> str:
    d = a.duration
    L: list[str] = []
    L.append(f"# Paired duration analysis: {a.controller_a} vs {a.controller_b}\n")
    L.append(
        "> **SIMULATED seconds, scripted controllers, Panda arm in PyBullet. Not robot throughput, not reset time.**\n"
    )
    L.append(
        f"{a.n_trial_pairs} trial pairs collapse to **{a.n_scenarios} distinct start scenarios** "
        f"({a.n_replayed_scenarios} scenario(s) replayed identically by several trials). Inference uses the "
        f"{a.n_scenarios} scenarios, not {a.n_trial_pairs}.\n"
    )
    L.append("## Result\n")
    L.append(
        f"- Scenario-weighted mean duration: A {d.mean_a:.3f} s, B {d.mean_b:.3f} s; paired difference "
        f"(A-B) **{d.mean_diff_a_minus_b:.3f} s** (95% bootstrap interval {d.diff_interval.ci_low:.3f} to "
        f"{d.diff_interval.ci_high:.3f}, {a.n_scenarios} scenarios)."
    )
    if d.rel_interval:
        r = d.rel_interval
        L.append(
            f"- Relative change of B vs A: **{100 * r.mean:.1f}%** (95% interval {100 * r.ci_low:.1f}% to "
            f"{100 * r.ci_high:.1f}%)."
        )
    L.append(
        f"- B was faster in {d.n_a_greater} scenarios, slower in {d.n_b_greater}, tied in {d.n_ties} "
        f"(exact sign test p = {d.sign_test_p_two_sided:.4g}; descriptive: the {a.n_scenarios} scenarios are a "
        "bounded perturbation set, not a random sample of a population)."
    )
    tw = a.trial_weighted
    L.append(
        f"- Trial-weighted (what a raw table shows): A {tw['mean_a_s']:.3f} s, B {tw['mean_b_s']:.3f} s, "
        f"{100 * tw['relative_change_b_vs_a']:.1f}% change over {int(tw['n_trial_pairs'])} pairs. This weights "
        "the replayed nominal scenario many times; it is reported only so the difference is visible.\n"
    )
    L.append("## By condition\n")
    L.append("| condition | pairs | distinct scenarios | mean A (s) | mean B (s) | A-B (s) | sd A | sd B |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for c in a.condition_table:
        L.append(
            f"| {c['condition']} | {c['n_pairs']} | {c['distinct_scenarios']} | {c['mean_a_s']:.3f} | "
            f"{c['mean_b_s']:.3f} | {c['mean_diff_a_minus_b_s']:.3f} | {c['sd_a_s']:.3f} | {c['sd_b_s']:.3f} |"
        )
    L.append(
        "\nsd = 0 means every trial in that condition replayed the same physical scenario bit-for-bit.\n"
    )
    L.append("## What the speed costs (paired, scenario-weighted)\n")
    L.append("| quantity | A | B | A-B | 95% interval of A-B | B larger / A larger / tie |")
    L.append("|---|---:|---:|---:|---|---|")
    for t in a.tradeoffs:
        L.append(
            f"| {t.name} ({t.unit}) | {t.mean_a:.4g} | {t.mean_b:.4g} | {t.mean_diff_a_minus_b:.4g} | "
            f"{t.diff_interval.ci_low:.4g} to {t.diff_interval.ci_high:.4g} | "
            f"{t.n_b_greater} / {t.n_a_greater} / {t.n_ties} |"
        )
    if a.phases:
        L.append("\n## Where the time goes (one nominal trial per controller, from recorded actions)\n")
        L.append("| controller | approach (s) | carry (s) | release + dwell (s) | trace length (s) |")
        L.append("|---|---:|---:|---:|---:|")
        for c, p in a.phases.items():
            L.append(
                f"| {c} | {p['approach_s']:.2f} | {p['carry_s']:.2f} | {p['release_and_dwell_s']:.2f} | "
                f"{p['total_s']:.2f} |"
            )
    if a.controller_params:
        L.append("\n## Controller parameters (the treatments)\n")
        for c, p in a.controller_params.items():
            L.append(f"- **{c}**: `{json.dumps(p, sort_keys=True)}`")
    L.append("\n## Limits\n")
    L += [f"- {c}" for c in a.caveats]
    if a.unpaired:
        L.append("\n## Unpaired / excluded\n")
        L += [f"- {u}" for u in a.unpaired]
    return "\n".join(L) + "\n"
