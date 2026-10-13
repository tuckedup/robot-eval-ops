"""export_summary: summary.md / summary.csv / summary.json / plots/ / report.html for one or more sessions.

Uses only the public EvalService API. Every planned trial is a row in summary.csv; every metric block carries
the session ids it was computed from, and sources list run directories and manifest/artifact paths
(relative to the data home)."""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from robotevalops.core.service import EvalService
from robotevalops.metrics.compute import GroupMetrics
from robotevalops.reporting.data import PROVENANCE_NOTES, ReportData, build_report_data, trial_rows
from robotevalops.reporting.html import LIMITATIONS, render_html
from robotevalops.reporting.plots import plot_durations, plot_failure_categories, plot_success_by_condition
from robotevalops.util import atomic_write_text, utcnow

ALL_FORMATS = ("md", "csv", "json", "html")


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _group_row(g: GroupMetrics) -> list[Any]:
    return [
        g.planned,
        g.attempted,
        g.completed,
        g.failed,
        g.aborted,
        g.unscored,
        g.evaluable,
        g.success_per_attempt.fmt(),
        g.success_per_evaluable.fmt(),
    ]


COUNT_HEADERS = [
    "planned",
    "attempted",
    "completed",
    "failed",
    "aborted",
    "unscored",
    "evaluable",
    "success/attempted",
    "success/evaluable",
]


def render_markdown(data: ReportData) -> str:
    m = data.metrics
    lines = ["# RobotEvalOps summary", ""]
    if m.banner:
        lines += [f"> **{m.banner}**", ""]
    for p in m.provenances:
        if p in PROVENANCE_NOTES and p != "mock":
            lines += [f"> {PROVENANCE_NOTES[p]}", ""]
    lines += [
        f"- Sessions: {', '.join(f'`{s}`' for s in m.session_ids) or 'none'}",
        f"- Provenance: {', '.join(m.provenances) or 'none'}; controller types: "
        f"{', '.join(m.controller_types) or 'none'}",
        f"- Generated: {utcnow().isoformat()}",
        "",
        "## Results (planned / attempted / completed / failed / aborted / unscored)",
        "",
        _md_table(["scope", *COUNT_HEADERS], [["ALL", *_group_row(m.overall)]]),
        "",
        "## By controller and condition",
        "",
        _md_table(
            [
                "controller",
                "type",
                "provenance",
                "condition",
                *COUNT_HEADERS,
                "intervention rate",
                "infra-abort rate",
                "recording pass rate",
            ],
            [
                [
                    g.key["controller_id"],
                    g.key["controller_type"],
                    g.key["provenance"],
                    g.key["condition"],
                    *_group_row(g),
                    g.intervention_rate.fmt(),
                    g.infra_abort_rate.fmt(),
                    g.recording_pass_rate.fmt(),
                ]
                for g in m.by_controller_condition
            ],
        ),
        "",
        "## Durations (recorded values only)",
        "",
        m.overall.duration.note,
        m.overall.reset_duration.note,
        "",
        "## Paired comparison",
        "",
    ]
    if not data.comparisons:
        lines += ["Fewer than two controllers: no paired comparison.", ""]
    for c in data.comparisons:
        lines += [
            f"### {c.controller_a} vs {c.controller_b}",
            "",
            _md_table(
                [
                    "condition",
                    "pairs",
                    "both",
                    "A only",
                    "B only",
                    "neither",
                    "A success",
                    "B success",
                    "exact McNemar p",
                ],
                [
                    [
                        x.condition,
                        x.pairs,
                        x.both,
                        x.a_only,
                        x.b_only,
                        x.neither,
                        x.a_success.fmt(),
                        x.b_success.fmt(),
                        "n/a" if x.p_value_exact_mcnemar is None else f"{x.p_value_exact_mcnemar:.4f}",
                    ]
                    for x in [c.overall, *c.by_condition]
                ],
            ),
            "",
            c.caveat,
            "",
        ]
        if c.unpaired:
            lines += ["Not analysed as pairs:", ""]
            lines += [f"- {u.condition} #{u.trial_index}: {u.reason}" for u in c.unpaired] + [""]
    a = m.overall.artifacts
    lines += [
        "## Failure categories",
        "",
        _md_table(["class", "trials"], [[k, v] for k, v in data.failures.class_totals.items()]),
        "",
        data.failures.note,
        "",
        "## QA and artifact completeness",
        "",
        f"- artifact completeness: {a.completeness.fmt()} (expected {a.expected}, missing {a.missing})",
        f"- checksums: verified {a.checksum_verified}, mismatch {a.checksum_mismatch}, "
        f"unverified {a.checksum_unverified}; agreement {a.checksum_agreement.fmt()}",
        f"- recording quality pass rate: {m.overall.recording_pass_rate.fmt()}",
        "",
        "## Warnings",
        "",
    ]
    ws = m.warnings + [w for g in m.by_controller_condition for w in g.warnings]
    lines += [f"- {w}" for w in ws] or ["- none"]
    lines += ["", "## Limitations", ""] + [f"- {x}" for x in LIMITATIONS]
    lines += ["", "## Data sources", ""]
    for b in data.bundles:
        lines.append(
            f"- session `{b.session.session_id}` ({b.session.name}): run dir `{b.run_dir_rel}`, manifest "
            f"`{b.run_dir_rel}/manifest.json` ({'present' if b.manifest_exists else 'not found'}), "
            f"eval_config_hash `{b.session.eval_config_hash}`"
        )
    return "\n".join(lines) + "\n"


def build_summary_json(data: ReportData, rows: list[dict[str, Any]]) -> dict[str, Any]:
    sessions = []
    for b in data.bundles:
        s = b.session
        cfg = b.eval_config
        sessions.append(
            {
                "session_id": s.session_id,
                "name": s.name,
                "state": s.state.value,
                "provenance": s.provenance.value,
                "backend": s.backend,
                "eval_config_hash": s.eval_config_hash,
                "git_commit": s.git_commit,
                "software": s.software,
                "run_dir": b.run_dir_rel,
                "manifest": f"{b.run_dir_rel}/manifest.json",
                "manifest_exists": b.manifest_exists,
                "controllers": [
                    {
                        "controller_id": c.controller_id,
                        "type": c.type.value,
                        "version": c.version,
                        "config_hash": c.config_hash,
                        "artifact_sha256": c.artifact_sha256,
                    }
                    for c in (cfg.controllers if cfg else [])
                ],
                "conditions": [c.model_dump(mode="json") for c in (cfg.conditions if cfg else [])],
                "base_seed": cfg.base_seed if cfg else None,
                "trials_per_condition": cfg.trials_per_condition if cfg else None,
            }
        )
    sources = [
        {
            "trial_id": t.trial_id,
            "session_id": t.session_id,
            "artifacts": [f"runs/{t.session_id}/{a.relpath}" for a in t.artifacts],
        }
        for t in data.trials
    ]
    return {
        "generated_at": utcnow().isoformat(),
        "provenance": data.metrics.provenances,
        "controller_types": data.metrics.controller_types,
        "banner": data.metrics.banner,
        "session_ids": data.metrics.session_ids,
        "sessions": sessions,
        "metrics": data.metrics.model_dump(mode="json"),
        "failures": data.failures.model_dump(mode="json"),
        "comparisons": [c.model_dump(mode="json") for c in data.comparisons],
        "limitations": LIMITATIONS,
        "trials": rows,
        "sources": sources,
    }


def export_summary(
    service: EvalService,
    session_ids: Sequence[str],
    out_dir: str | Path,
    *,
    formats: Sequence[str] = ALL_FORMATS,
) -> dict[str, Path]:
    """Write the requested formats into out_dir and return {name: path}. Plots are written whenever md or
    html is requested (html embeds them)."""
    unknown = set(formats) - set(ALL_FORMATS)
    if unknown:
        raise ValueError(f"unknown export format(s) {sorted(unknown)}; choose from {ALL_FORMATS}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    data = build_report_data(service, session_ids)
    rows = trial_rows(data.bundles)
    written: dict[str, Path] = {}
    plot_paths: dict[str, Path] = {}
    if "html" in formats or "md" in formats:
        pdir = out / "plots"
        pdir.mkdir(exist_ok=True)
        banner = data.metrics.banner
        plot_paths = {
            "success": plot_success_by_condition(data.metrics, pdir / "success_by_condition.png"),
            "failures": plot_failure_categories(data.failures, banner, pdir / "failure_categories.png"),
            "duration": plot_durations(data.trials, banner, pdir / "duration.png"),
        }
        for k, p in plot_paths.items():
            written[f"plot_{k}"] = p
    if "csv" in formats:
        path = out / "summary.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            cols = list(rows[0].keys()) if rows else ["session_id", "trial_id"]
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        written["csv"] = path
    if "md" in formats:
        atomic_write_text(out / "summary.md", render_markdown(data))
        written["md"] = out / "summary.md"
    if "json" in formats:
        atomic_write_text(
            out / "summary.json", json.dumps(build_summary_json(data, rows), indent=2, allow_nan=False)
        )
        written["json"] = out / "summary.json"
    if "html" in formats:
        atomic_write_text(out / "report.html", render_html(data, plot_paths))
        written["html"] = out / "report.html"
    return written
