from __future__ import annotations

from pathlib import Path

from robotevalops import scoring

T = Path(__file__).resolve().parents[2] / "docs" / "templates"


def test_csv_templates_are_header_only():
    for name in ("scoring-agreement.csv", "reset-time-log.csv"):
        lines = (T / name).read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1, f"{name} must contain only a header (no fabricated data)"


def test_empty_agreement_template_gives_undefined_not_a_number():
    r = scoring.agreement_from_csv(T / "scoring-agreement.csv")
    assert r.n == 0 and r.percent_agreement is None and r.cohen_kappa is None
