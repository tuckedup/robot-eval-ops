# ruff: noqa: E501, B023
"""V6/V7: reproducibility (same config twice, pairing across controllers) and mock-banner coverage of exports."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

pytest.importorskip("pybullet")

from robotevalops.adapters.sim_pybullet import PyBulletPandaAdapter  # noqa: E402
from robotevalops.cli.main import app  # noqa: E402
from robotevalops.controllers.base import configs_dir, load_conditions, load_controller_specs  # noqa: E402
from robotevalops.controllers.scripted_pick_place import ScriptedPickPlaceController  # noqa: E402
from robotevalops.core.runner import Runner  # noqa: E402
from robotevalops.core.scheduler import build_schedule  # noqa: E402
from robotevalops.core.service import EvalService  # noqa: E402
from robotevalops.schemas import EvalConfig, Provenance  # noqa: E402

cli = CliRunner()


def _cfg() -> EvalConfig:
    conds = {c.name: c for c in load_conditions(configs_dir() / "conditions" / "sim_conditions.yaml")}
    specs = load_controller_specs(configs_dir() / "controllers" / "sim_scripted.yaml")
    return EvalConfig(
        name="repro",
        provenance=Provenance.SIMULATION,
        backend="pybullet_panda",
        controllers=specs,
        conditions=[conds["nominal"], conds["object_position"]],
        trials_per_condition=2,
        base_seed=4242,
    )


def _run_once(home: Path):
    svc = EvalService(home)
    cfg = _cfg()
    s = svc.create_session("repro", Provenance.SIMULATION, "pybullet_panda", eval_config=cfg)
    svc.plan_trials(s.session_id, cfg)
    Runner(
        svc, lambda sess: PyBulletPandaAdapter(render=False), lambda spec: ScriptedPickPlaceController(spec)
    ).run_session(s.session_id)
    return svc.list_trials(s.session_id)


@pytest.mark.physics
def test_same_sim_config_twice_reproduces_schedule_pose_and_outcome(tmp_path: Path) -> None:
    a = _run_once(tmp_path / "a")
    b = _run_once(tmp_path / "b")
    key = lambda t: (t.schedule_position, t.controller_id, t.condition_name, t.trial_index, t.seed)  # noqa: E731
    assert [key(t) for t in a] == [key(t) for t in b]  # exact schedule, ids differ but not the plan
    assert {t.trial_id for t in a}.isdisjoint({t.trial_id for t in b})
    for ta, tb in zip(a, b, strict=True):
        assert (ta.state, ta.task_outcome, ta.termination_reason) == (
            tb.state,
            tb.task_outcome,
            tb.termination_reason,
        )
        pa, pb = ta.evidence["block_final_pos"], tb.evidence["block_final_pos"]
        assert max(abs(x - y) for x, y in zip(pa, pb, strict=True)) < 1e-3, (pa, pb)
        assert ta.evidence["applied_condition"] == tb.evidence["applied_condition"]
        assert ta.duration_s == pytest.approx(tb.duration_s, abs=1e-6)
    # pairing: identical seed AND identical applied block offset across the two controllers in a cell
    cells: dict[tuple[str, int], list] = {}
    for t in a:
        cells.setdefault((t.condition_name, t.trial_index), []).append(t)
    for (cond, idx), ts in cells.items():
        assert len(ts) == 2 and ts[0].controller_id != ts[1].controller_id
        assert ts[0].seed == ts[1].seed, (cond, idx)
        assert ts[0].evidence["applied_condition"] == ts[1].evidence["applied_condition"]
    off = [
        t.evidence["applied_condition"].get("block_offset_m")
        for t in a
        if t.condition_name == "object_position"
    ]
    assert all(o is not None and max(abs(v) for v in o) <= 0.04 + 1e-12 for o in off)
    assert len({tuple(o) for o in off}) >= 2  # trial indices really re-draw


def test_schedule_is_pure_function_and_seed_independent_of_controller() -> None:
    cfg = _cfg()
    s1, s2 = build_schedule(cfg), build_schedule(cfg)
    assert [
        (p.schedule_position, p.controller.controller_id, p.condition.name, p.trial_index, p.seed) for p in s1
    ] == [
        (p.schedule_position, p.controller.controller_id, p.condition.name, p.trial_index, p.seed) for p in s2
    ]
    only_b = cfg.model_copy(update={"controllers": [cfg.controllers[1]]})
    seeds_b = {(p.condition.name, p.trial_index): p.seed for p in build_schedule(only_b)}
    seeds_all = {(p.condition.name, p.trial_index): p.seed for p in s1}
    assert seeds_b == seeds_all  # adding/removing a controller does not change anyone's seeds
    other = cfg.model_copy(update={"base_seed": cfg.base_seed + 1})
    assert {p.seed for p in build_schedule(other)}.isdisjoint({p.seed for p in s1})


# ----------------------------------------------------------------------------- mock banners in every export
def _mock_session(home: Path) -> str:
    cfg = Path(__file__).resolve().parents[2] / "configs" / "eval_smoke_mock.yaml"
    r = cli.invoke(
        app, ["session", "create", "--name", "v", "--config", str(cfg), "--home", str(home), "--json"]
    )
    sid = json.loads(r.output)["session_id"]
    assert cli.invoke(app, ["session", "plan", sid, "--home", str(home)]).exit_code == 0
    assert cli.invoke(app, ["session", "run", sid, "--home", str(home)]).exit_code == 0
    r = cli.invoke(app, ["report", "export", sid, "--home", str(home), "--json"])
    assert r.exit_code == 0, r.output
    return sid


BANNER = "MOCK FIXTURE"


def test_mock_banner_in_html_md_json_and_plots(tmp_path: Path) -> None:
    home = tmp_path / "home"
    sid = _mock_session(home)
    out = home / "reports" / sid
    for name in ("report.html", "summary.md", "summary.json"):
        assert BANNER in (out / name).read_text(encoding="utf-8"), name
    assert (out / "plots").is_dir() and list((out / "plots").glob("*.png"))


def test_mock_provenance_is_in_every_csv_row_even_without_banner_line(tmp_path: Path) -> None:
    home = tmp_path / "home"
    sid = _mock_session(home)
    rows = list(csv.DictReader((home / "reports" / sid / "summary.csv").open(encoding="utf-8")))
    assert rows and all(
        r["provenance"] == "mock" and r["score_source"] in ("mock_fixture", "none") for r in rows
    )


def test_mock_banner_text_also_in_csv(tmp_path: Path) -> None:
    home = tmp_path / "home"
    sid = _mock_session(home)
    assert BANNER in (home / "reports" / sid / "summary.csv").read_text(encoding="utf-8")


def test_sim_export_never_says_so101_or_hardware_performance(tmp_path: Path) -> None:
    demo = Path(__file__).resolve().parents[2] / "data" / "demo_sim" / "reports"
    if not demo.exists():
        pytest.skip("no demo_sim reports")
    for f in demo.rglob("summary.md"):
        txt = f.read_text(encoding="utf-8")
        assert "not the SO-101" in txt and "not hardware" in txt.lower()
        assert "learned" in txt.lower() and "not learned policies" in txt
