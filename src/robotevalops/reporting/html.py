# ruff: noqa: E501
"""Self-contained HTML report (jinja2, autoescaped; plots embedded as base64 PNG)."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from jinja2 import Environment

from robotevalops.metrics.compute import GroupMetrics, Rate
from robotevalops.reporting.data import PROVENANCE_NOTES, ReportData

LIMITATIONS = [
    "The controllers evaluated by this repository are scripted, state-based programs reading simulator "
    "state; they are not learned policies and not trained checkpoints.",
    "Simulation results use a PyBullet Panda arm with rendered simulator frames. This is not the SO-101 "
    "arm and not physical hardware; no conclusion about real-robot performance follows.",
    "Mock-provenance results are seeded fixtures and are never evidence of robotics performance.",
    "Visual-only conditions (lighting, background, occlusion) do not change what a state-based controller "
    "reads; they say nothing about the visual robustness of a learned policy.",
    "Small sample sizes: Wilson intervals are wide and any difference between controllers is descriptive. "
    "p-values from so few discordant pairs do not support significance claims.",
    "Scoring agreement between independent human scorers and reset-time improvements are not measured by "
    "this report; they need independent human measurement (see docs/evaluation-protocol.md).",
]

TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RobotEvalOps report</title>
<style>
body{font-family:system-ui,Segoe UI,sans-serif;margin:1.5rem auto;max-width:1100px;padding:0 1rem;color:#1a1a1a;background:#fff}
h1,h2,h3{margin-top:1.6em} table{border-collapse:collapse;margin:.6em 0;font-size:.85rem}
th,td{border:1px solid #bbb;padding:.25em .5em;text-align:left;vertical-align:top} th{background:#eee}
.banner{padding:.8em 1em;margin:.5em 0;border:2px solid #b00;background:#fff3cd;font-weight:bold}
.warn{color:#8a4b00} code{font-size:.85em} img{max-width:100%;height:auto;border:1px solid #ddd}
.small{font-size:.8rem;color:#444}
@media (prefers-color-scheme: dark){body{background:#161616;color:#eee}th{background:#333}
th,td{border-color:#666}.banner{background:#4a3b00;color:#fff;border-color:#f66}.warn{color:#ffb454}.small{color:#bbb}}
</style></head><body>
<h1>RobotEvalOps evaluation report</h1>

<h2 id="purpose">Purpose</h2>
<p>Report the outcome of a robot-policy evaluation: how many trials were planned, attempted and scored, what
each controller achieved under each condition, how trials failed, and how complete the recorded evidence is.
It states denominators and uncertainty; it does not claim more than the data supports.</p>

<h2 id="provenance">Provenance</h2>
{% for b in banners %}<div class="banner">{{ b }}</div>{% endfor %}
<p>Provenance in this report: <b>{{ provenances|join(", ") }}</b>. Controller types: <b>{{ controller_types|join(", ") }}</b>.
Provenance (where data came from) and controller type (who produced actions) are separate fields.</p>

<h2 id="methods">Methods</h2>
<ul>
<li>Task rubric <code>{{ rubric }}</code>: block entirely inside the target region, released, and stays for the dwell time within the attempt timeout; any operator assistance prevents an autonomous success.</li>
{% for k, v in definitions.items() %}<li><b>{{ k }}</b>: {{ v }}</li>{% endfor %}
<li>Wilson 95% intervals on every rate. Durations: recorded values only (mean/median/min/max with n); nothing imputed.</li>
<li>Pairing: the same seed per (condition, trial index) across controllers; paired comparison lists discordant pairs and an exact McNemar p-value, which does not support significance claims at this n.</li>
</ul>

<h2 id="configs">Configurations</h2>
{% for s in sessions %}
<h3>Session {{ s.name }} <code>{{ s.session_id }}</code></h3>
<p class="small">state {{ s.state }}, provenance {{ s.provenance }}, backend {{ s.backend }}, eval_config_hash <code>{{ s.eval_config_hash }}</code>, base_seed {{ s.base_seed }}</p>
{% if s.controllers %}<table><tr><th>controller</th><th>type</th><th>version</th><th>config hash</th><th>config</th></tr>
{% for c in s.controllers %}<tr><td>{{ c.controller_id }}</td><td>{{ c.type }}</td><td>{{ c.version }}</td><td><code>{{ c.config_hash }}</code></td><td><code>{{ c.config_json }}</code></td></tr>{% endfor %}</table>
<table><tr><th>condition</th><th>kind</th><th>version</th><th>params</th><th>affects controller state</th></tr>
{% for c in s.conditions %}<tr><td>{{ c.name }}</td><td>{{ c.kind }}</td><td>{{ c.version }}</td><td><code>{{ c.params_json }}</code></td><td>{{ c.affects_controller_state }}</td></tr>{% endfor %}</table>
<p class="small">Per-trial seeds are in summary.csv (seed column).</p>
{% else %}<p class="warn">No eval config stored with this session.</p>{% endif %}
{% endfor %}

<h2 id="results">Results</h2>
{% if warnings %}<ul>{% for w in warnings %}<li class="warn">{{ w }}</li>{% endfor %}</ul>{% endif %}
{{ results_table|safe }}
{{ breakdown_table|safe }}
<img alt="success by condition" src="data:image/png;base64,{{ plots.success }}">

<h2 id="comparison">Per-condition comparison</h2>
{% if comparisons %}{% for c in comparisons %}
<h3>{{ c.controller_a }} vs {{ c.controller_b }}</h3>
<table><tr><th>condition</th><th>pairs</th><th>both</th><th>A only</th><th>B only</th><th>neither</th><th>A success</th><th>B success</th><th>exact McNemar p</th></tr>
{% for r in c.rows %}<tr><td>{{ r.condition }}</td><td>{{ r.pairs }}</td><td>{{ r.both }}</td><td>{{ r.a_only }}</td><td>{{ r.b_only }}</td><td>{{ r.neither }}</td><td>{{ r.a }}</td><td>{{ r.b }}</td><td>{{ r.p }}</td></tr>{% endfor %}</table>
<p class="small">{{ c.caveat }}</p>
{% if c.unpaired %}<p class="warn">Not analysed as pairs ({{ c.unpaired|length }}):</p><ul>{% for u in c.unpaired %}<li>{{ u.condition }} #{{ u.trial_index }}: {{ u.reason }}</li>{% endfor %}</ul>{% endif %}
{% endfor %}{% else %}<p>Fewer than two controllers: no paired comparison.</p>{% endif %}

<h2 id="failures">Failures</h2>
<img alt="failure categories" src="data:image/png;base64,{{ plots.failures }}">
{{ failure_table|safe }}
<img alt="durations" src="data:image/png;base64,{{ plots.duration }}">

<h2 id="qa">QA and artifact completeness</h2>
{{ qa_table|safe }}
{% if qa_flags %}<p>QA flags: {{ qa_flags }}</p>{% endif %}

<h2 id="limitations">Limitations</h2>
<ul>{% for l in limitations %}<li>{{ l }}</li>{% endfor %}</ul>

<h2 id="sources">Data sources</h2>
<table><tr><th>session id</th><th>run dir (relative to data home)</th><th>manifest</th><th>git commit</th><th>software</th></tr>
{% for s in sessions %}<tr><td><code>{{ s.session_id }}</code></td><td><code>{{ s.run_dir }}</code></td><td><code>{{ s.manifest }}</code> ({{ "present" if s.manifest_exists else "not found" }})</td><td>{{ s.git_commit or "unknown" }}</td><td class="small">{{ s.software }}</td></tr>{% endfor %}</table>
<p class="small">Generated from the EvalService database; every figure above is computed from the recorded trial rows listed in summary.csv.</p>
</body></html>
"""


def _fmt_dur(g: GroupMetrics) -> str:
    d = g.duration
    if d.n == 0:
        return "no recorded durations"
    out = f"n={d.n}, mean {d.mean:.2f}, median {d.median:.2f}, min {d.min:.2f}, max {d.max:.2f}"
    if d.p95 is not None:
        out += f", p95 {d.p95:.2f}"
    return out


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    from markupsafe import escape

    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><tr>{head}</tr>{body}</table>"


def _rate(r: Rate) -> str:
    return r.fmt()


def count_headers() -> list[str]:
    return ["planned", "attempted", "completed", "failed", "aborted", "unscored", "evaluable"]


def count_cells(g: GroupMetrics) -> list[Any]:
    return [g.planned, g.attempted, g.completed, g.failed, g.aborted, g.unscored, g.evaluable]


def render_html(data: ReportData, plot_paths: dict[str, Path]) -> str:
    m = data.metrics
    results_rows = [
        ["ALL", ", ".join(m.provenances), ", ".join(m.controller_types)]
        + count_cells(m.overall)
        + [_rate(m.overall.success_per_attempt), _rate(m.overall.success_per_evaluable)]
    ]
    results_table = _table(
        [
            "scope",
            "provenance",
            "controller type",
            *count_headers(),
            "autonomous success / attempted",
            "autonomous success / evaluable",
        ],
        results_rows,
    )
    brows = [
        [
            g.key.get("controller_id"),
            g.key.get("controller_type"),
            g.key.get("provenance"),
            g.key.get("condition"),
            *count_cells(g),
            _rate(g.success_per_attempt),
            _rate(g.success_per_evaluable),
            _rate(g.intervention_rate),
            _rate(g.infra_abort_rate),
            _rate(g.recording_pass_rate),
            _fmt_dur(g),
        ]
        for g in m.by_controller_condition
    ]
    breakdown_table = _table(
        [
            "controller",
            "type",
            "provenance",
            "condition",
            *count_headers(),
            "success / attempted",
            "success / evaluable",
            "intervention rate",
            "infra-abort rate",
            "recording pass rate",
            "duration",
        ],
        brows,
    )
    failure_table = _table(
        [
            "controller",
            "type",
            "provenance",
            "condition",
            "class",
            "state",
            "termination",
            "outcome",
            "intervention",
            "count",
        ],
        [
            [
                r.controller_id,
                r.controller_type,
                r.provenance,
                r.condition,
                r.failure_class,
                r.state,
                r.termination_reason,
                r.task_outcome,
                r.intervention,
                r.count,
            ]
            for r in data.failures.rows
        ],
    )
    a = m.overall.artifacts
    qa_table = _table(
        ["metric", "value"],
        [
            ["artifact completeness", _rate(a.completeness)],
            ["expected artifacts", a.expected],
            ["missing / pending / failed", a.missing],
            ["quarantined", a.quarantined],
            ["checksum verified", a.checksum_verified],
            ["checksum mismatch", a.checksum_mismatch],
            ["checksum unverified (hash recorded only)", a.checksum_unverified],
            ["checksum agreement (verified / transferred)", _rate(a.checksum_agreement)],
            ["recording quality pass rate", _rate(m.overall.recording_pass_rate)],
            ["scored but excluded by quality = fail", m.overall.quality_excluded],
        ],
    )
    comparisons = [
        {
            "controller_a": c.controller_a,
            "controller_b": c.controller_b,
            "caveat": c.caveat,
            "unpaired": [u.model_dump() for u in c.unpaired],
            "rows": [
                {
                    "condition": x.condition,
                    "pairs": x.pairs,
                    "both": x.both,
                    "a_only": x.a_only,
                    "b_only": x.b_only,
                    "neither": x.neither,
                    "a": _rate(x.a_success),
                    "b": _rate(x.b_success),
                    "p": "n/a (no discordant pairs)"
                    if x.p_value_exact_mcnemar is None
                    else f"{x.p_value_exact_mcnemar:.4f}",
                }
                for x in [c.overall, *c.by_condition]
            ],
        }
        for c in data.comparisons
    ]
    sessions = []
    for b in data.bundles:
        cfg = b.eval_config
        s = b.session
        sessions.append(
            {
                "session_id": s.session_id,
                "name": s.name,
                "state": s.state.value,
                "provenance": s.provenance.value,
                "backend": s.backend,
                "eval_config_hash": s.eval_config_hash,
                "git_commit": s.git_commit,
                "software": ", ".join(f"{k} {v}" for k, v in s.software.items()),
                "run_dir": b.run_dir_rel,
                "manifest": f"{b.run_dir_rel}/manifest.json",
                "manifest_exists": b.manifest_exists,
                "base_seed": cfg.base_seed if cfg else None,
                "controllers": [
                    {
                        "controller_id": c.controller_id,
                        "type": c.type.value,
                        "version": c.version,
                        "config_hash": c.config_hash,
                        "config_json": json.dumps(c.config, sort_keys=True),
                    }
                    for c in (cfg.controllers if cfg else [])
                ],
                "conditions": [
                    {
                        "name": c.name,
                        "kind": c.kind,
                        "version": c.version,
                        "params_json": json.dumps(c.params, sort_keys=True),
                        "affects_controller_state": c.affects_controller_state,
                    }
                    for c in (cfg.conditions if cfg else [])
                ],
            }
        )
    banners = [PROVENANCE_NOTES[p] for p in m.provenances if p in PROVENANCE_NOTES]
    if m.banner and m.banner not in banners:
        banners.insert(0, m.banner)
    env = Environment(autoescape=True)
    plots = {k: base64.b64encode(Path(v).read_bytes()).decode("ascii") for k, v in plot_paths.items()}
    qa_flags = ", ".join(f"{k}: {v}" for k, v in data.failures.qa_flag_counts.items())
    return env.from_string(TEMPLATE).render(
        banners=banners,
        provenances=m.provenances or ["none"],
        controller_types=m.controller_types or ["none"],
        rubric=_rubric(data),
        definitions=m.denominator_definitions,
        sessions=sessions,
        warnings=m.warnings + [w for g in m.by_controller_condition for w in g.warnings],
        results_table=results_table,
        breakdown_table=breakdown_table,
        comparisons=comparisons,
        failure_table=failure_table,
        qa_table=qa_table,
        qa_flags=qa_flags,
        limitations=LIMITATIONS,
        plots=plots,
    )


def _rubric(data: ReportData) -> str:
    versions = sorted({t.rubric_version for t in data.trials})
    return ", ".join(versions) if versions else "rubric-v1"
