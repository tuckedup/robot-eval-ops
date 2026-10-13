from __future__ import annotations

import csv
import json

from typer.testing import CliRunner

from robotevalops.cli.main import app

runner = CliRunner()


def _inv(svc, *args):
    return runner.invoke(app, ["report", *args, "--home", str(svc.home)])


def test_metrics_json_and_text(seeded):
    svc, sess = seeded
    r = _inv(svc, "metrics", sess.session_id, "--json")
    assert r.exit_code == 0, r.output
    js = json.loads(r.output)
    assert js["overall"]["planned"] == 12 and js["overall"]["attempted"] == 11
    r = _inv(svc, "metrics", sess.session_id)
    assert r.exit_code == 0 and "planned 12 | attempted 11" in r.output


def test_compare_cli(seeded):
    svc, sess = seeded
    r = _inv(svc, "compare", sess.session_id, "--a", "ctrl0", "--b", "ctrl1", "--json")
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["controller_a"] == "ctrl0"
    r = _inv(svc, "compare", sess.session_id, "--a", "ctrl0", "--b", "ctrl1")
    assert "does not support significance claims" in r.output


def test_score_and_edit_cli_protections(seeded):
    from robotevalops import scoring

    svc, sess = seeded
    tid = scoring.list_unscored(svc, sess.session_id)[0].trial_id
    base = ["score", tid, "--outcome", "success", "--scorer", "alice", "--intervention", "none"]
    r = _inv(svc, *base)
    assert r.exit_code == 0, r.output
    r = _inv(svc, *base)  # second first-score is refused
    assert r.exit_code == 1 and "ScoreProtectionError" in r.output
    r = _inv(
        svc,
        "edit-score",
        tid,
        "--outcome",
        "failure",
        "--editor",
        "bob",
        "--reason",
        " ",
        "--intervention",
        "none",
    )
    assert r.exit_code == 1
    r = _inv(
        svc,
        "edit-score",
        tid,
        "--outcome",
        "failure",
        "--editor",
        "bob",
        "--reason",
        "re-watched video",
        "--intervention",
        "none",
    )
    assert r.exit_code == 0, r.output
    assert len(svc.list_score_edits(tid)) == 1


def test_export_and_html_cli(seeded, tmp_path):
    svc, sess = seeded
    out = tmp_path / "o"
    r = _inv(
        svc, "export", sess.session_id, "--out-dir", str(out), "--format", "csv", "--format", "json", "--json"
    )
    assert r.exit_code == 0, r.output
    assert (out / "summary.csv").is_file() and (out / "summary.json").is_file()
    assert not (out / "report.html").exists()
    with open(out / "summary.csv", encoding="utf-8") as fh:
        assert len(list(csv.DictReader(fh))) == 12
    r = _inv(svc, "html", sess.session_id)
    assert r.exit_code == 0, r.output
    assert (svc.home / "reports" / sess.session_id / "report.html").is_file()


def test_unknown_session_and_dashboard_check(svc):
    r = _inv(svc, "metrics", "nope", "--json")
    assert r.exit_code == 1 and "NotFoundError" in r.output
    r = runner.invoke(app, ["report", "dashboard", "--check", "--home", str(svc.home), "--port", "8777"])
    assert r.exit_code == 0 and "streamlit" in r.output and "8777" in r.output and "app.py" in r.output


def test_agreement_cli(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text(
        "trial_id,scorer_a,outcome_a,scorer_b,outcome_b,rubric_version,notes\n"
        "t1,ann,success,bo,success,rubric-v1,\nt2,ann,failure,bo,success,rubric-v1,\n",
        encoding="utf-8",
    )
    r = runner.invoke(app, ["report", "agreement", str(p), "--json"])
    assert r.exit_code == 0 and json.loads(r.output)["percent_agreement"] == 0.5
