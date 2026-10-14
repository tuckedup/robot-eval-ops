# ruff: noqa: E501
"""Plots for the paired analysis. Okabe-Ito colours (colour-blind safe), direct labels, thin lines, n in titles."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from robotevalops.analysis.paired_duration import Analysis  # noqa: E402

COLORS = ["#0072B2", "#D55E00"]  # A blue, B vermillion; also distinguished by label and linestyle


def _trace(path: Path) -> tuple[dict[str, list[float]], list[float]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    names = json.loads(lines[0])["state_names"]
    rows = [json.loads(x) for x in lines[1:] if x.strip()]
    cols = {n: [r["state"][i] for r in rows] for i, n in enumerate(names)}
    return cols, [r["t"] for r in rows]


def plot_trajectories(traces: dict[str, Path], out: Path, title: str) -> Path:
    """End-effector height, gripper width and block height vs simulated time, one nominal trial per controller."""
    fig, axes = plt.subplots(3, 1, figsize=(7.5, 7), sharex=True)
    for (cid, path), color, ls in zip(traces.items(), COLORS, ("-", "--"), strict=False):
        cols, t = _trace(path)
        for ax, key in zip(axes, ("ee_z", "gripper_width", "block_z"), strict=True):
            ax.plot(t, cols[key], color=color, ls=ls, lw=2, label=cid)
    for ax, lab in zip(axes, ("end-effector z (m)", "gripper width (m)", "block z (m)"), strict=True):
        ax.set_ylabel(lab)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(alpha=0.25, lw=0.5)
    axes[0].legend(frameon=False, loc="upper right")
    axes[-1].set_xlabel("simulated time (s)")
    fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)
    return out


def plot_scenario_diffs(a: Analysis, out: Path) -> Path:
    d = a.duration
    fig, ax = plt.subplots(figsize=(7.5, 4))
    vals = sorted(d.per_scenario_diffs)
    ax.plot(range(len(vals)), vals, "o", color=COLORS[0], ms=8, mec="white", mew=1.5)
    ax.axhline(0, color="#555", lw=1)
    ax.axhline(d.mean_diff_a_minus_b, color=COLORS[1], lw=2)
    ax.axhspan(d.diff_interval.ci_low, d.diff_interval.ci_high, color=COLORS[1], alpha=0.15, lw=0)
    ax.text(
        len(vals) - 0.5,
        d.mean_diff_a_minus_b,
        f" mean {d.mean_diff_a_minus_b:.2f} s",
        color="#333",
        va="bottom",
        ha="right",
    )
    ax.set_xlabel(f"start scenario (sorted; n={a.n_scenarios} distinct, from {a.n_trial_pairs} trial pairs)")
    ax.set_ylabel("duration A - B (simulated s)")
    ax.set_title(
        "Paired difference per distinct start scenario (band: 95% bootstrap interval of the mean)", fontsize=9
    )
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)
    return out
