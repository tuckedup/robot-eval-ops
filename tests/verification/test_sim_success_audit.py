# ruff: noqa: E501, B023
"""V1: is simulated success real? Adversarial controllers + dwell-timer attacks on the real PyBullet adapter."""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from robotevalops.errors import RobotEvalOpsError

pytest.importorskip("pybullet")

from robotevalops.adapters.base import Action  # noqa: E402
from robotevalops.adapters.sim_pybullet import (  # noqa: E402
    HOME_JOINTS,
    TARGET_CENTER,
    TARGET_HALF,
    PyBulletPandaAdapter,
    corners_inside_square,
)
from robotevalops.schemas import TerminationReason  # noqa: E402

from .sim_helpers import (  # noqa: E402
    CONDS,
    FreezeAfter,
    HoldAboveNeverRelease,
    NoOp,
    Pusher,
    ShiftedPlace,
    run,
)

pytestmark = pytest.mark.physics


def test_noop_controller_is_failure(tmp_path: Path) -> None:
    r = run(NoOp(), tmp_path, timeout_s=12)
    assert r.termination_reason == TerminationReason.TIMEOUT and r.task_success is False
    assert r.evidence["lift_m"] == pytest.approx(0.0, abs=1e-3)


def test_close_gripper_never_lift_is_failure(tmp_path: Path) -> None:
    r = run(FreezeAfter("lift", 0.0), tmp_path, timeout_s=15)
    assert r.task_success is False
    assert r.evidence["lift_m"] < 0.005 and r.evidence["released"] is False


def test_hold_block_above_target_without_release_is_failure(tmp_path: Path) -> None:
    r = run(HoldAboveNeverRelease(), tmp_path, timeout_s=40)
    ev = r.evidence
    assert ev["lift_m"] > 0.1  # it really was lifted and carried
    assert ev["all_corners_inside"] is True  # block sits inside the region ...
    assert ev["released"] is False  # ... but is still held
    assert r.task_success is False and ev["dwell_s_max"] == 0.0


def test_block_dropped_straddling_region_edge_is_failure(tmp_path: Path) -> None:
    r = run(ShiftedPlace(0.0, 0.05), tmp_path, timeout_s=40)
    ev = r.evidence
    assert ev["released"] is True and ev["lift_m"] > 0.1
    assert ev["all_corners_inside"] is False
    assert 0.0 < ev["in_target_fraction"] < 1.0  # genuinely straddling
    assert r.task_success is False


class _AimedPusher(Pusher):
    """Aim the sweep so the block comes to rest near the region centre (empirically -0.09 m)."""

    def act(self, o):  # type: ignore[no-untyped-def]
        t = o.state["target_center_world"]
        st = {**o.state, "target_center_world": [t[0], t[1] - 0.09, 0.0]}
        return super().act(type(o)(o.t, st, o.image))


def test_pushing_block_without_grasp_should_not_count_as_pick_place_success(tmp_path: Path) -> None:
    r = run(_AimedPusher(), tmp_path, timeout_s=40)
    assert r.evidence["lift_m"] < 0.005 and r.evidence["both_finger_contact_steps"] == 0  # never grasped
    assert r.task_success is False, "a push-only run was scored as a pick-and-place success"


@pytest.mark.parametrize("dwell_s", [0.0, -1.0, float("nan")])
def test_nonpositive_dwell_is_refused(tmp_path: Path, dwell_s: float) -> None:
    """VF-02 (fixed): a non-positive dwell must be refused, never let a no-op controller succeed."""
    with pytest.raises(RobotEvalOpsError):
        run(NoOp(), tmp_path, dwell_s=dwell_s, timeout_s=5)


# --------------------------- dwell timer attacks (test-side teleport of the block, product code untouched)
def _teleport(ad: PyBulletPandaAdapter, x: float, y: float, z: float = 0.0202) -> None:
    ad.p.resetBasePositionAndOrientation(ad._block, [x, y, z], [0, 0, 0, 1], physicsClientId=ad._cid)
    ad.p.resetBaseVelocity(ad._block, [0, 0, 0], [0, 0, 0], physicsClientId=ad._cid)


def _fresh(dwell_required: float = 2.0) -> PyBulletPandaAdapter:
    ad = PyBulletPandaAdapter(render=False)
    ad.reset(CONDS["nominal"], 1)
    ad._dwell_required = dwell_required
    return ad


def _step(ad: PyBulletPandaAdapter, finger: float = 0.04) -> bool:
    ad.act(Action([*HOME_JOINTS, finger, 20.0]))
    return ad.step().done


def test_dwell_resets_when_block_leaves_even_for_one_step() -> None:
    ad = _fresh()
    try:
        cx, cy = TARGET_CENTER
        _teleport(ad, cx, cy)
        for _ in range(30):
            assert _step(ad) is False
        assert ad._dwell == pytest.approx(1.5)
        _teleport(ad, cx, cy + 0.2)  # bounce out for exactly one control step
        _step(ad)
        assert ad._dwell == 0.0
        _teleport(ad, cx, cy)
        for _ in range(30):
            assert _step(ad) is False  # 1.5 s again: must NOT have inherited the first 1.5 s
        done = [_step(ad) for _ in range(12)]
        assert done.index(True) >= 9  # success only after a full fresh 2.0 s
    finally:
        ad.close()


def test_dwell_requires_continuous_full_2s_before_success() -> None:
    ad = _fresh()
    try:
        _teleport(ad, *TARGET_CENTER)
        n = 0
        while not _step(ad):
            n += 1
            assert n < 100
        assert n + 1 == 40  # 40 control steps at 20 Hz = 2.0 s exactly, not fewer
    finally:
        ad.close()


def test_gripper_closed_while_block_inside_never_accumulates_dwell() -> None:
    ad = _fresh()
    try:
        _teleport(ad, *TARGET_CENTER)
        for _ in range(60):
            if _step(ad, finger=0.0):  # fingers commanded closed -> width < 0.06
                pytest.fail("success reported with gripper not open")
        assert ad._dwell == 0.0
    finally:
        ad.close()


def test_tolerance_boundary_one_millimetre_each_side() -> None:
    cx, cy = TARGET_CENTER
    q = np.array([0, 0, 0, 1.0])
    edge = TARGET_HALF - 0.02
    assert corners_inside_square(np.array([cx, cy + edge - 0.001, 0.02]), q, TARGET_CENTER, TARGET_HALF)
    assert not corners_inside_square(np.array([cx, cy + edge + 0.001, 0.02]), q, TARGET_CENTER, TARGET_HALF)
    # yawed 45 deg: footprint corners reach 0.0283 m from the centre, centre-only logic would accept
    s, c = math.sin(math.radians(22.5)), math.cos(math.radians(22.5))
    yaw45 = np.array([0, 0, s, c])
    assert not corners_inside_square(
        np.array([cx, cy + edge - 0.001, 0.02]), yaw45, TARGET_CENTER, TARGET_HALF
    )


def test_block_on_edge_with_centre_inside_is_not_success() -> None:
    """Centre inside the region but footprint straddling the edge for 3 s must not succeed."""
    ad = _fresh()
    try:
        cx, cy = TARGET_CENTER
        _teleport(ad, cx, cy + TARGET_HALF - 0.005)  # centre 5 mm inside the edge
        for _ in range(60):
            assert _step(ad) is False
        assert ad._dwell == 0.0
    finally:
        ad.close()


# --------------------------- audit of the shipped demo evidence (read-only)
DEMO_SIM = Path(__file__).resolve().parents[2] / "data" / "demo_sim"


def _sim_traces() -> list[Path]:
    return sorted((DEMO_SIM / "runs").glob("*/trials/*/trace.jsonl")) if DEMO_SIM.exists() else []


def _db_row(trial_id: str) -> tuple[str, dict[str, Any]] | None:
    db = DEMO_SIM / "robotevalops.db"
    if not db.exists():
        return None
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        row = con.execute(
            "SELECT task_outcome, evidence_json FROM trials WHERE trial_id=?", (trial_id,)
        ).fetchone()
    finally:
        con.close()
    return (row[0], json.loads(row[1])) if row else None


@pytest.mark.skipif(not _sim_traces(), reason="data/demo_sim not present")
@pytest.mark.parametrize("trace", _sim_traces(), ids=lambda p: p.parent.name[:8])
def test_demo_sim_trace_physical_consistency(trace: Path) -> None:
    lines = trace.read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0])
    rows = [json.loads(x) for x in lines[1:]]
    names = header["state_names"]
    assert header["provenance"] == "simulation"
    t = [r["t"] for r in rows]
    assert all(b > a for a, b in zip(t, t[1:], strict=False)), "timestamps not strictly increasing"
    for r in rows:
        assert all(math.isfinite(v) for v in r["state"] + r["action"])
    bz = [r["state"][names.index("block_z")] for r in rows]
    gw = [r["state"][names.index("gripper_width")] for r in rows]
    bx = [r["state"][names.index("block_x")] for r in rows]
    by = [r["state"][names.index("block_y")] for r in rows]
    for i in range(1, len(rows)):  # teleport detector: carried speed is < 0.5 m/s => < 0.05 m per 0.1 s row
        d = math.dist((bx[i - 1], by[i - 1], bz[i - 1]), (bx[i], by[i], bz[i]))
        assert d < 0.15, f"block jumped {d:.3f} m between rows {i - 1}->{i}"
    got = _db_row(trace.parent.name)
    if got is None:
        pytest.skip("trial not in db")
    outcome, evidence = got
    if outcome == "success":
        assert max(bz) - min(bz[:3]) > 0.05, "success without a lift in the block z history"
        inner = TARGET_HALF - 0.02 + 1e-6
        end_t = t[-1]
        win = [i for i in range(len(t)) if t[i] >= end_t - 1.9]
        ok = [
            abs(bx[i] - TARGET_CENTER[0]) <= inner
            and abs(by[i] - TARGET_CENTER[1]) <= inner
            and gw[i] >= 0.06
            for i in win
        ]
        assert all(ok), "trace tail (>= 1.9 s) is not continuously inside+open"
        assert evidence["dwell_s"] >= 2.0 - 1e-6
