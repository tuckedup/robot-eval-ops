"""Matplotlib plots (Agg backend). Colourblind-safe Okabe-Ito palette, labelled axes, n shown in labels."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from robotevalops.metrics.compute import MetricsReport  # noqa: E402
from robotevalops.metrics.failures import FailureReport  # noqa: E402
from robotevalops.schemas import TrialRecord  # noqa: E402

OKABE_ITO = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#F0E442", "#000000"]
HATCHES = ["", "//", "..", "xx", "\\\\", "--"]


def _title(base: str, banner: str | None) -> str:
    return f"{base}\n{banner}" if banner else base


def plot_success_by_condition(report: MetricsReport, out: Path) -> Path:
    cells = report.by_controller_condition
    conds = sorted({g.key["condition"] for g in cells})
    ctrls = sorted({(g.key["controller_id"], g.key["controller_type"]) for g in cells})
    fig, ax = plt.subplots(figsize=(max(6.0, 1.6 * len(conds) + 2), 4.4))
    width = 0.8 / max(1, len(ctrls))
    for ci, (cid, ctype) in enumerate(ctrls):
        xs: list[float] = []
        ys: list[float] = []
        lo: list[float] = []
        hi: list[float] = []
        labels: list[str] = []
        for i, cond in enumerate(conds):
            g = next((x for x in cells if x.key["controller_id"] == cid and x.key["condition"] == cond), None)
            if g is None or g.success_per_attempt.rate is None:
                continue
            r = g.success_per_attempt
            assert r.rate is not None
            xs.append(i + ci * width - 0.4 + width / 2)
            ys.append(r.rate)
            lo.append(r.rate - (r.ci_low or 0.0))
            hi.append((r.ci_high or 0.0) - r.rate)
            labels.append(f"{r.k}/{r.n}")
        bars = ax.bar(
            xs,
            ys,
            width * 0.9,
            yerr=[lo, hi] if xs else None,
            capsize=3,
            color=OKABE_ITO[ci % len(OKABE_ITO)],
            hatch=HATCHES[ci % len(HATCHES)],
            edgecolor="black",
            label=f"{cid} ({ctype})",
        )
        for b, lab in zip(bars, labels, strict=True):
            ax.annotate(
                lab,
                (b.get_x() + b.get_width() / 2, 0.02),
                ha="center",
                fontsize=7,
                color="white",
                bbox={"boxstyle": "round,pad=0.1", "fc": "black", "alpha": 0.6, "lw": 0},
            )
    ax.set_xticks(range(len(conds)))
    ax.set_xticklabels(conds, rotation=20, ha="right")
    ax.set_ylim(0, 1.25)
    ax.set_xlabel("condition")
    ax.set_ylabel("autonomous success / attempted (Wilson 95% CI)")
    ax.set_title(
        _title(
            "Autonomous success by condition and controller (label k/n = successes/attempted)", report.banner
        ),
        fontsize=9,
    )
    if ctrls:
        ax.legend(fontsize=8, loc="upper right", ncol=2)
    else:
        ax.text(0.5, 0.5, "no trials", ha="center", transform=ax.transAxes)
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)
    return out


def plot_failure_categories(failures: FailureReport, banner: str | None, out: Path) -> Path:
    # stacked horizontal bars: per controller, counts per failure class
    classes = sorted({r.failure_class for r in failures.rows})
    ctrls = sorted({r.controller_id for r in failures.rows})
    fig, ax = plt.subplots(figsize=(7.5, max(2.8, 0.8 * len(ctrls) + 1.8)))
    left = [0] * len(ctrls)
    for ki, cls in enumerate(classes):
        vals = [
            sum(r.count for r in failures.rows if r.controller_id == c and r.failure_class == cls)
            for c in ctrls
        ]
        ax.barh(
            ctrls,
            vals,
            left=left,
            color=OKABE_ITO[ki % len(OKABE_ITO)],
            hatch=HATCHES[ki % len(HATCHES)],
            edgecolor="black",
            label=cls,
        )
        left = [a + b for a, b in zip(left, vals, strict=True)]
    ax.set_xlabel(f"trials (planned total n={failures.total_trials}; every planned trial is counted)")
    ax.set_ylabel("controller")
    ax.set_title(_title("Outcome / failure categories", banner), fontsize=9)
    if classes:
        ax.legend(fontsize=7, loc="center left", bbox_to_anchor=(1.0, 0.5))
    else:
        ax.text(0.5, 0.5, "no trials", ha="center", transform=ax.transAxes)
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)
    return out


def plot_durations(trials: Sequence[TrialRecord], banner: str | None, out: Path) -> Path:
    ctrls = sorted({t.controller_id for t in trials})
    data = [
        [t.duration_s for t in trials if t.controller_id == c and t.duration_s is not None] for c in ctrls
    ]
    fig, ax = plt.subplots(figsize=(6.5, 4.0))
    if any(data):
        shown = [(c, d) for c, d in zip(ctrls, data, strict=True) if d]
        ax.boxplot([d for _, d in shown], showfliers=False)
        for i, (_, d) in enumerate(shown, start=1):
            step = 0.3 / max(1, len(d))
            ax.scatter(
                [i - 0.15 + k * step for k in range(len(d))],
                d,
                s=14,
                color=OKABE_ITO[1],
                edgecolor="black",
                zorder=3,
            )
        ax.set_xticks(range(1, len(shown) + 1))
        ax.set_xticklabels([f"{c}\n(n={len(d)} recorded)" for c, d in shown])
    else:
        ax.text(0.5, 0.5, "no recorded durations", ha="center", transform=ax.transAxes)
    ax.set_xlabel("controller (only trials with a recorded duration)")
    ax.set_ylabel("trial duration (s)")
    ax.set_title(_title("Trial duration (box = IQR/median, dots = individual trials)", banner), fontsize=9)
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)
    return out
