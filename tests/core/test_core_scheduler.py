from __future__ import annotations

from conftest import make_config
from robotevalops.core.scheduler import build_schedule
from robotevalops.util import derive_seed


def test_count_is_controllers_x_conditions_x_trials():
    assert len(build_schedule(make_config(2, 5, 10))) == 100
    assert len(build_schedule(make_config(2, 3, 2))) == 12
    assert len(build_schedule(make_config(1, 1, 1))) == 1


def test_seeds_paired_across_controllers():
    cfg = make_config(2, 3, 4, base_seed=11)
    sched = build_schedule(cfg)
    cells: dict[tuple[str, int], set[int]] = {}
    for p in sched:
        cells.setdefault((p.condition.name, p.trial_index), set()).add(p.seed)
        assert p.seed == derive_seed(11, p.condition.name, p.trial_index)
    assert len(cells) == 12
    assert all(len(v) == 1 for v in cells.values())


def test_order_and_positions_hand_computed():
    cfg = make_config(2, 2, 2, condition_names=["A", "B"])
    got = [
        (p.schedule_position, p.condition.name, p.trial_index, p.controller.controller_id)
        for p in build_schedule(cfg)
    ]
    assert got == [
        (0, "A", 0, "ctrl0"),
        (1, "A", 0, "ctrl1"),
        (2, "A", 1, "ctrl0"),
        (3, "A", 1, "ctrl1"),
        (4, "B", 0, "ctrl0"),
        (5, "B", 0, "ctrl1"),
        (6, "B", 1, "ctrl0"),
        (7, "B", 1, "ctrl1"),
    ]


def test_same_config_same_schedule_and_seed_changes_with_base_seed():
    a = build_schedule(make_config(2, 5, 10, base_seed=3))
    b = build_schedule(make_config(2, 5, 10, base_seed=3))
    c = build_schedule(make_config(2, 5, 10, base_seed=4))
    assert a == b
    assert [p.seed for p in a] != [p.seed for p in c]


def test_different_cells_get_different_seeds():
    seeds = {(p.condition.name, p.trial_index): p.seed for p in build_schedule(make_config(1, 5, 10))}
    assert len(set(seeds.values())) == 50
