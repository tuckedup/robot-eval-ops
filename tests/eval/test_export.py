from __future__ import annotations

import csv
import json

from eval_seed import seed_session

from robotevalops.reporting.export import export_summary
from robotevalops.schemas import Provenance


def test_export_all_formats(seeded, tmp_path):
    svc, sess = seeded
    out = tmp_path / "rep"
    files = export_summary(svc, [sess.session_id], out)
    for k in ("md", "csv", "json", "html", "plot_success", "plot_failures", "plot_duration"):
        assert files[k].is_file() and files[k].stat().st_size > 0
    with open(files["csv"], encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 12  # every planned trial, including the never-attempted one
    assert sum(r["attempted"] == "False" for r in rows) == 1
    assert {r["session_id"] for r in rows} == {sess.session_id}
    js = json.loads(files["json"].read_text(encoding="utf-8"))
    ov = js["metrics"]["overall"]
    # seed: 12 planned; ctrl1/cond1#2 never attempted -> 11 attempted
    assert (ov["planned"], ov["attempted"]) == (12, 11)
    assert (ov["completed"], ov["failed"], ov["aborted"]) == (9, 1, 1)
    assert ov["unscored"] == 3  # infra, abort, completed-unscored
    assert js["session_ids"] == [sess.session_id]
    assert js["sessions"][0]["eval_config_hash"] == sess.eval_config_hash
    assert js["sessions"][0]["controllers"][0]["config_hash"]
    assert js["sessions"][0]["manifest"] == f"runs/{sess.session_id}/manifest.json"
    assert len(js["trials"]) == 12 and len(js["sources"]) == 12
    md = files["md"].read_text(encoding="utf-8")
    assert sess.session_id in md and "Limitations" in md and "never attempted" in md


def test_html_contents_and_no_overclaims(seeded, tmp_path):
    svc, sess = seeded
    html = export_summary(svc, [sess.session_id], tmp_path / "r")["html"].read_text(encoding="utf-8")
    for s in (
        "Limitations",
        "Provenance",
        "scripted",
        "not the SO-101",
        "Panda",
        sess.session_id,
        "data:image/png;base64",
        "Data sources",
        "does not support significance claims",
    ):
        assert s in html or s.lower() in html.lower(), s
    assert "p95" not in html  # n is small: never reported
    assert "MOCK FIXTURE" not in html  # simulation provenance
    low = html.lower()
    for bad in ("outperform", "statistically significant", "proves"):
        assert bad not in low


def test_mock_session_banner_in_every_format(svc, tmp_path):
    sess = seed_session(svc, Provenance.MOCK, "mockrun")
    files = export_summary(svc, [sess.session_id], tmp_path / "m")
    banner = "MOCK FIXTURE — not evidence of robotics performance"
    assert banner in files["html"].read_text(encoding="utf-8")
    assert banner in files["md"].read_text(encoding="utf-8")
    assert json.loads(files["json"].read_text(encoding="utf-8"))["banner"] == banner


def test_unknown_format_rejected(seeded, tmp_path):
    import pytest

    svc, sess = seeded
    with pytest.raises(ValueError):
        export_summary(svc, [sess.session_id], tmp_path / "x", formats=("pdf",))
