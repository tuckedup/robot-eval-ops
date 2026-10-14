"""Audit A8: same-named controllers with different config, or trials from different sessions, never pool."""

from __future__ import annotations

from eval_helpers import NONE, OK, PASS, C, S, make_trial

from robotevalops.metrics.compare import compare_controllers
from robotevalops.metrics.compute import compute_metrics


def _win(ctrl, cond, idx, *, session="s1", cfg="h1", seed=7):
    return make_trial(
        controller_id=ctrl,
        condition=cond,
        trial_index=idx,
        state=C,
        outcome=S,
        reason=OK,
        intervention=NONE,
        quality=PASS,
        session_id=session,
        controller_config_hash=cfg,
        seed=seed,
    )


def test_same_name_different_config_hash_gets_separate_rows_and_a_warning():
    ts = [_win("A", "c", 0, cfg="h1"), _win("A", "c", 1, cfg="h2"), _win("B", "c", 0)]
    m = compute_metrics(ts)
    a_rows = [g for g in m.by_controller if g.key["controller_id"] == "A"]
    assert {g.key["controller_config_hash"] for g in a_rows} == {"h1", "h2"} and all(
        g.planned == 1 for g in a_rows
    )
    assert m.overall.pooled_controller_ids == ["A"]
    assert any("different config hashes" in w for w in m.overall.warnings)
    assert all("rubric_version" in g.key for g in m.by_controller)


def test_different_controllers_with_different_hashes_do_not_trigger_the_pooling_warning():
    m = compute_metrics([_win("A", "c", 0, cfg="h1"), _win("B", "c", 0, cfg="h2")])
    assert m.overall.pooled_controller_ids == [] and not any(
        "different config" in w for w in m.overall.warnings
    )


def test_pairs_never_cross_sessions():
    ts = [
        _win("A", "c", 0, session="s1"),
        _win("B", "c", 0, session="s2"),
    ]  # same index, different experiments
    cmp = compare_controllers(ts, "A", "B")
    assert cmp.overall.pairs == 0
    assert sorted((i.session_id, i.reason) for i in cmp.unpaired) == [
        ("s1", "missing_partner"),
        ("s2", "missing_partner"),
    ]


def test_pairs_form_within_a_session_and_identity_is_reported():
    ts = [_win("A", "c", i, session="s1") for i in range(2)] + [
        _win("B", "c", i, session="s1") for i in range(2)
    ]
    ts += [_win("A", "c", 0, session="s2", cfg="h9"), _win("B", "c", 0, session="s2")]
    cmp = compare_controllers(ts, "A", "B")
    assert cmp.overall.pairs == 3 and cmp.session_ids == ["s1", "s2"]
    assert cmp.controller_config_hashes["A"] == ["h1", "h9"]
    assert any("different config hashes" in n for n in cmp.notes)
    assert "same session" in cmp.pairing_unit
