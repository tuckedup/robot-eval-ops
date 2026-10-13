from __future__ import annotations

import pytest
from eval_helpers import ASS, FL, NONE, OK, PASS, TO, C, F, S, make_trial

from robotevalops.metrics.compare import SIGNIFICANCE_CAVEAT, compare_controllers
from robotevalops.schemas import TerminationReason


def _t(ctrl, cond, idx, win, **kw):
    if win:
        return make_trial(
            controller_id=ctrl,
            condition=cond,
            trial_index=idx,
            state=C,
            outcome=S,
            reason=OK,
            intervention=NONE,
            quality=PASS,
            **kw,
        )
    return make_trial(
        controller_id=ctrl,
        condition=cond,
        trial_index=idx,
        state=C,
        outcome=FL,
        reason=TO,
        intervention=NONE,
        quality=PASS,
        **kw,
    )


def test_discordant_counts_and_exact_mcnemar():
    # condition x: idx0 both, idx1 A-only, idx2 B-only, idx3 neither; condition y: 5 B-only, 1 A-only
    ts = []
    for idx, (a, b) in enumerate([(1, 1), (1, 0), (0, 1), (0, 0)]):
        ts += [_t("A", "x", idx, a), _t("B", "x", idx, b)]
    for idx in range(5):
        ts += [_t("A", "y", idx, 0), _t("B", "y", idx, 1)]
    ts += [_t("A", "y", 5, 1), _t("B", "y", 5, 0)]
    cmp = compare_controllers(ts, "A", "B")
    x = next(c for c in cmp.by_condition if c.condition == "x")
    y = next(c for c in cmp.by_condition if c.condition == "y")
    assert (x.both, x.a_only, x.b_only, x.neither, x.pairs) == (1, 1, 1, 1, 4)
    assert (y.both, y.a_only, y.b_only, y.neither, y.pairs) == (0, 1, 5, 0, 6)
    assert y.p_value_exact_mcnemar == pytest.approx(14 / 64)  # hand computed: 2*(1+6)/2^6
    assert x.p_value_exact_mcnemar == 1.0  # b=c=1 -> min(1, 2*(1+2)/4)
    assert (cmp.overall.a_only, cmp.overall.b_only) == (2, 6)
    assert cmp.overall.p_value_exact_mcnemar == pytest.approx(2 * (1 + 8 + 28) / 256)  # n=8, <=2: 37
    assert cmp.caveat == SIGNIFICANCE_CAVEAT and "does not" in cmp.caveat and "significance" in cmp.caveat
    assert cmp.unpaired == []


def test_unpaired_and_ineligible_are_listed_not_dropped():
    ts = [
        _t("A", "x", 0, 1),
        _t("B", "x", 0, 1),
        _t("A", "x", 1, 1),  # B partner missing
        _t("A", "x", 2, 1),
        make_trial(
            controller_id="B", condition="x", trial_index=2, state=F, reason=TerminationReason.INFRA_FAILURE
        ),  # B infra failed
        make_trial(
            controller_id="A", condition="x", trial_index=3, state=C, outcome=S, reason=OK, intervention=ASS
        ),
        _t("B", "x", 3, 1),  # A scored but assisted -> evaluable, counts as non-success for A
        _t("A", "x", 4, 1, seed=1),
        _t("B", "x", 4, 1, seed=2),  # seed mismatch
    ]
    cmp = compare_controllers(ts, "A", "B")
    reasons = {(i.trial_index, i.reason) for i in cmp.unpaired}
    assert reasons == {(1, "missing_partner"), (2, "not_evaluable_b"), (4, "seed_mismatch")}
    assert cmp.overall.pairs == 2  # idx0 (both) and idx3 (B-only: A assisted)
    assert (cmp.overall.both, cmp.overall.b_only) == (1, 1)
    assert any("could not be analysed" in n for n in cmp.notes)


def test_no_discordant_pairs_has_no_p_value():
    ts = [_t("A", "x", 0, 1), _t("B", "x", 0, 1)]
    assert compare_controllers(ts, "A", "B").overall.p_value_exact_mcnemar is None
