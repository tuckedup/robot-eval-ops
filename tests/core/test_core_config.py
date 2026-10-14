from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from robotevalops.config import ConfigError, load_eval_config
from robotevalops.schemas import Provenance

CTRL = [
    {"controller_id": "a", "type": "scripted", "version": "1", "config": {"x": 1}},
    {"controller_id": "b", "type": "scripted", "version": "1"},
]
COND = [
    {"name": "n1", "kind": "nominal"},
    {"name": "n2", "kind": "lighting"},
    {"name": "n3", "kind": "nominal"},
]


def write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def base(**kw):
    d = {"name": "t", "provenance": "mock", "backend": "mock", "trials_per_condition": 2}
    d.update(kw)
    return d


def test_inline_lists(tmp_path):
    cfg = load_eval_config(write(tmp_path / "e.yaml", base(controllers=CTRL, conditions=COND)))
    assert cfg.planned_count == 2 * 3 * 2 == 12
    assert cfg.provenance == Provenance.MOCK


def test_from_paths_relative_to_config_dir(tmp_path):
    write(tmp_path / "lists" / "c.yaml", CTRL)
    write(tmp_path / "lists" / "k.yaml", {"conditions": COND})  # mapping form is accepted too
    cfg = load_eval_config(
        write(tmp_path / "e.yaml", base(controllers_from="lists/c.yaml", conditions_from="lists/k.yaml"))
    )
    assert [c.controller_id for c in cfg.controllers] == ["a", "b"]
    assert len(cfg.conditions) == 3


def test_from_paths_relative_to_repo_root(tmp_path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    write(tmp_path / "configs" / "controllers" / "c.yaml", CTRL)
    write(tmp_path / "configs" / "conditions" / "k.yaml", COND)
    cfg = load_eval_config(
        write(
            tmp_path / "configs" / "sub" / "e.yaml",
            base(controllers_from="configs/controllers/c.yaml", conditions_from="configs/conditions/k.yaml"),
        )
    )
    assert cfg.planned_count == 12


def test_errors_are_clear(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_eval_config(tmp_path / "missing.yaml")
    with pytest.raises(ConfigError, match="missing 'controllers'"):
        load_eval_config(write(tmp_path / "a.yaml", base(conditions=COND)))
    with pytest.raises(ConfigError, match="not both"):
        load_eval_config(
            write(tmp_path / "b.yaml", base(controllers=CTRL, controllers_from="x.yaml", conditions=COND))
        )
    with pytest.raises(ConfigError, match="controllers_from 'nope.yaml' not found"):
        load_eval_config(write(tmp_path / "c.yaml", base(controllers_from="nope.yaml", conditions=COND)))
    with pytest.raises(ConfigError, match=r"invalid controllers\[0\]"):
        load_eval_config(
            write(tmp_path / "d.yaml", base(controllers=[{"controller_id": "z"}], conditions=COND))
        )
    with pytest.raises(ConfigError, match="duplicate controller_id"):
        load_eval_config(write(tmp_path / "e.yaml", base(controllers=[CTRL[0], CTRL[0]], conditions=COND)))
    with pytest.raises(ConfigError, match="duplicate condition"):
        load_eval_config(write(tmp_path / "f.yaml", base(controllers=CTRL, conditions=[COND[0], COND[0]])))
    with pytest.raises(ConfigError, match="inconsistent"):
        load_eval_config(
            write(tmp_path / "g.yaml", base(provenance="simulation", controllers=CTRL, conditions=COND))
        )
    with pytest.raises(ConfigError, match="trials_per_condition"):
        load_eval_config(
            write(tmp_path / "h.yaml", base(trials_per_condition=0, controllers=CTRL, conditions=COND))
        )
    bad = tmp_path / "i.yaml"
    bad.write_text("a: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_eval_config(bad)
    with pytest.raises(ConfigError, match="non-empty YAML list"):
        write(tmp_path / "empty.yaml", [])
        load_eval_config(write(tmp_path / "j.yaml", base(controllers_from="empty.yaml", conditions=COND)))


def test_shipped_eval_templates_parse_from_the_package():
    from robotevalops.controllers.base import configs_dir

    root = configs_dir()
    assert "robotevalops" in root.parts  # shipped inside the package, not a repo-root directory
    expected = {"eval_smoke_mock": 12, "eval_smoke_sim": 10, "eval_full_sim": 100}
    for name, count in expected.items():
        path = root / f"{name}.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert raw["provenance"] in ("mock", "simulation")
        assert (path.parent / raw["controllers_from"]).is_file()  # resolved next to the config
        assert (path.parent / raw["conditions_from"]).is_file()
        assert load_eval_config(path).planned_count == count
