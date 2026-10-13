"""Write the fault-injection report (Markdown + JSON) from ACTUAL executions. Nothing is pre-filled:
unexecuted cases (e.g. F10 when core is missing) are shown as NOT EXECUTED."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from robotevalops.schemas import FaultResult
from robotevalops.util import atomic_write_text, software_versions, utcnow


def _executed(r: FaultResult) -> bool:
    return bool(r.details.get("executed", True))


def summarize(results: list[FaultResult]) -> dict[str, Any]:
    return {
        "total": len(results),
        "executed": sum(_executed(r) for r in results),
        "passed": sum(1 for r in results if _executed(r) and r.passed),
        "failed": [r.case_id for r in results if _executed(r) and not r.passed],
        "not_executed": [r.case_id for r in results if not _executed(r)],
    }


def build_payload(results: list[FaultResult]) -> dict[str, Any]:
    return {
        "generated_at": utcnow().isoformat(),
        "environment": software_versions(),
        "fixtures": "synthetic (generated frames/states via TrialRecorder, provenance=mock); not robot data",
        "summary": summarize(results),
        "results": [
            {**r.model_dump(mode="json"), "executed": _executed(r), "passed": _executed(r) and r.passed}
            for r in results
        ],
    }


def render_markdown(payload: dict[str, Any]) -> str:
    s = payload["summary"]
    env = payload["environment"]
    out = [
        "# Fault-injection report",
        "",
        f"Generated: {payload['generated_at']} (by `robotevalops data faults`; regenerate, do not hand-edit)",
        "",
        f"Environment: Python {env.get('python', '?')} on {env.get('platform', '?')}; "
        + ", ".join(f"{k} {v}" for k, v in env.items() if k not in ("python", "platform")),
        "",
        f"Fixtures: {payload['fixtures']}.",
        "",
        f"**Result: {s['executed']} of {s['total']} cases executed, {s['passed']} passed.** "
        + (f"Failed: {', '.join(s['failed'])}. " if s["failed"] else "")
        + (f"NOT EXECUTED: {', '.join(s['not_executed'])}." if s["not_executed"] else ""),
        "",
        "A case passes only when the fault was detected, the evidence bytes were preserved, and a misleading "
        "success was prevented.",
        "",
        "| Case | Executed | Detected codes | Detected | Evidence preserved "
        "| Misleading success prevented | Passed |",
        "|---|---|---|---|---|---|---|",
    ]
    yn = {True: "yes", False: "NO"}
    for r in payload["results"]:
        if not r["executed"]:
            out.append(f"| {r['case_id']} | **NOT EXECUTED** | - | - | - | - | - |")
            continue
        out.append(
            f"| {r['case_id']} | yes | {', '.join(r['detected_codes']) or '-'} | {yn[r['detected']]} | "
            f"{yn[r['evidence_preserved']]} | {yn[r['misleading_success_prevented']]} | {yn[r['passed']]} |"
        )
    out += ["", "## Details", ""]
    for r in payload["results"]:
        out.append(f"### {r['case_id']}")
        out.append("")
        if not r["executed"]:
            out += [f"NOT EXECUTED: {r['message']}", ""]
            continue
        out += [
            f"- Fault: {r['description']}",
            f"- Expected code: `{r['expected_code']}`; executed at {r['executed_at']}",
            f"- Actionable message produced: {r['message']}",
            f"- Details: `{json.dumps(r['details'], default=str)}`",
            "",
        ]
    return "\n".join(out) + "\n"


def write_report(
    results: list[FaultResult],
    md_path: str | Path = "docs/fault-injection-report.md",
    json_path: str | Path | None = None,
) -> dict[str, Any]:
    payload = build_payload(results)
    md = Path(md_path)
    atomic_write_text(md, render_markdown(payload))
    atomic_write_text(
        Path(json_path) if json_path else md.with_suffix(".json"), json.dumps(payload, indent=2) + "\n"
    )
    return payload
