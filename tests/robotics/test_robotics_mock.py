"""Mock fixture adapter tests (no physics). Mock output is never robotics evidence."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

import cv2
import pytest

from robotevalops.adapters.base import Action
from robotevalops.adapters.mock import MOCK_LABEL, MockAdapter, mock_outcome
from robotevalops.controllers.base import (
    StopRequestedError,
    configs_dir,
    load_conditions,
    load_controller_specs,
)
from robotevalops.controllers.mock_scripted import MockScriptedController
from robotevalops.errors import RobotEvalOpsError
from robotevalops.schemas import Provenance, TerminationReason

CONDS = {c.name: c for c in load_conditions(configs_dir() / "conditions" / "mock_conditions.yaml")}
SPECS = {
    s.controller_id: s for s in load_controller_specs(configs_dir() / "controllers" / "mock_scripted.yaml")
}


def run(
    tmp_path: Path, seed: int = 3, cond: str = "nominal", ctl: str = "mock_scripted_a", faults=None, **kw
):
    a = MockAdapter(faults=faults, **kw)
    a.reset(CONDS[cond], seed)
    res = a.run_episode(MockScriptedController(SPECS[ctl]), tmp_path, 30.0, 2.0)
    return a, res


def read_trace(path: Path):
    consts: list[str] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    rows = [json.loads(x, parse_constant=lambda c: consts.append(c) or float("nan")) for x in lines]
    return rows[0], rows[1:], consts


def test_config_files_load_and_are_labelled():
    assert len(CONDS) == 3 and len(SPECS) == 2
    sim = load_conditions(configs_dir() / "conditions" / "sim_conditions.yaml")
    assert [c.kind for c in sim] == ["nominal", "object_position", "lighting", "background", "occlusion"]
    assert {c.kind: c.affects_controller_state for c in sim} == {
        "nominal": False,
        "object_position": True,
        "lighting": False,
        "background": False,
        "occlusion": False,
    }
    for c in sim:
        if c.kind in ("lighting", "background", "occlusion"):
            assert "not expected to react" in c.description
            assert "learned-policy" in c.description
    assert all("Not performance evidence" in c.description for c in CONDS.values())


def test_outcome_rule_matches_hand_computed_hash():
    cond, spec = CONDS["mock_state_shift"], SPECS["mock_scripted_b"]
    digest = hashlib.sha256(f"mock-outcome-v1|11|mock_state_shift|{spec.config_hash}".encode()).digest()
    u = int.from_bytes(digest[:8], "big") / 2**64
    ok, u2, p = mock_outcome(11, cond, spec.config_hash, skill=0.5)
    assert u2 == u and p == pytest.approx(0.35) and ok == (u < 0.35)


def test_same_seed_identical_outcome_and_trace(tmp_path):
    _, r1 = run(tmp_path / "a", seed=5)
    _, r2 = run(tmp_path / "b", seed=5)
    assert (r1.termination_reason, r1.task_success, r1.evidence) == (
        r2.termination_reason,
        r2.task_success,
        r2.evidence,
    )
    assert (tmp_path / "a" / "trace.jsonl").read_bytes() == (tmp_path / "b" / "trace.jsonl").read_bytes()


def test_different_seed_differs(tmp_path):
    _, r1 = run(tmp_path / "a", seed=5)
    _, r2 = run(tmp_path / "b", seed=6)
    assert (tmp_path / "a" / "trace.jsonl").read_bytes() != (tmp_path / "b" / "trace.jsonl").read_bytes()
    assert r1.evidence["u"] != r2.evidence["u"]
    outcomes = set()
    for s in range(40):
        a = MockAdapter()
        a.reset(CONDS["nominal"], s)
        outcomes.add(
            a.run_episode(
                MockScriptedController(SPECS["mock_scripted_b"]), tmp_path / f"s{s}", 30, 2
            ).task_success
        )
    assert outcomes == {True, False}


def test_controller_config_changes_outcome_probability_fields(tmp_path):
    _, ra = run(tmp_path / "a", ctl="mock_scripted_a")
    _, rb = run(tmp_path / "b", ctl="mock_scripted_b")
    assert ra.evidence["p"] == pytest.approx(0.8) and rb.evidence["p"] == pytest.approx(0.5)


def test_mock_provenance_label_and_recording_metadata(tmp_path):
    a, res = run(tmp_path)
    assert a.provenance == Provenance.MOCK and a.name == "mock"
    assert res.evidence["fixture"] == MOCK_LABEL == "mock — not performance evidence"
    header, rows, _ = read_trace(tmp_path / "trace.jsonl")
    assert header["provenance"] == "mock"
    assert res.recording.video_kind == "mock_synthetic_frames"
    assert res.recording.frames_written == res.recording.frames_expected == len(rows) == 30
    assert res.recording.completeness == 1.0
    assert (tmp_path / "video.mp4").stat().st_size > 0
    assert a.preflight().ok


def test_fault_infra_exception(tmp_path):
    with pytest.raises(RuntimeError, match="infra_exception"):
        run(tmp_path, faults={"infra_exception"})


def test_fault_recording_failure(tmp_path):
    _, res = run(tmp_path, faults={"recording_failure"})
    assert res.termination_reason == TerminationReason.RECORDING_FAILURE
    assert res.task_success is None and res.error and "recording_failure" in res.error


def test_fault_timeout(tmp_path):
    _, res = run(tmp_path, faults={"timeout"})
    assert res.termination_reason == TerminationReason.TIMEOUT
    assert res.task_success is False
    assert res.duration_s == pytest.approx(30.0)
    assert res.recording.trace_rows == 300


def test_fault_hang_until_stop_honours_request_stop(tmp_path):
    a = MockAdapter(faults={"hang_until_stop"}, max_hang_s=20)
    a.reset(CONDS["nominal"], 1)
    threading.Timer(0.3, a.request_stop).start()
    t0 = time.monotonic()
    res = a.run_episode(MockScriptedController(SPECS["mock_scripted_a"]), tmp_path, 30, 2)
    assert time.monotonic() - t0 < 5
    assert res.termination_reason == TerminationReason.SOFTWARE_STOP_REQUEST
    assert res.task_success is None


def test_fault_truncate_video_is_a_real_truncated_file(tmp_path):
    _, good = run(tmp_path / "good", seed=2)
    _, bad = run(tmp_path / "bad", seed=2, faults={"truncate_video"})
    good_size = (tmp_path / "good" / "video.mp4").stat().st_size
    bad_size = (tmp_path / "bad" / "video.mp4").stat().st_size
    assert 0 < bad_size < good_size * 0.5
    cap = cv2.VideoCapture(str(tmp_path / "bad" / "video.mp4"))
    frames = 0
    while cap.isOpened() and cap.read()[0]:
        frames += 1
    cap.release()
    assert frames < bad.recording.frames_written  # recorder claims 30; the file cannot deliver them


def test_fault_nonfinite_action_lands_in_trace(tmp_path):
    run(tmp_path, faults={"nonfinite_action"})
    _, rows, consts = read_trace(tmp_path / "trace.jsonl")
    assert "NaN" in consts
    assert rows[5]["action"][0] != rows[5]["action"][0]  # NaN


def test_fault_nonmonotonic_timestamps_lands_in_trace(tmp_path):
    run(tmp_path, faults={"nonmonotonic_timestamps"})
    _, rows, _ = read_trace(tmp_path / "trace.jsonl")
    ts = [r["t"] for r in rows]
    assert any(b < a for a, b in zip(ts, ts[1:], strict=False))
    assert ts[7] < ts[6]


def test_fault_drop_video_removes_the_file(tmp_path):
    _, res = run(tmp_path, faults={"drop_video"})
    assert not (tmp_path / "video.mp4").exists()
    assert (tmp_path / "trace.jsonl").exists()
    assert res.recording.video_relpath == "video.mp4"  # recorder claimed it; QA must catch the gap


def test_unknown_fault_rejected():
    with pytest.raises(RobotEvalOpsError, match="unknown mock fault"):
        MockAdapter(faults={"nope"})


def test_request_stop_idempotent_and_act_after_stop_raises():
    a = MockAdapter()
    a.reset(CONDS["nominal"], 1)
    assert a.stop_requested is False
    a.request_stop()
    a.request_stop()
    assert a.stop_requested is True
    with pytest.raises(StopRequestedError):
        a.act(Action([0.0]))
    with pytest.raises(StopRequestedError):
        a.step()
    with pytest.raises(StopRequestedError):
        a.reset(CONDS["nominal"], 2)


def test_run_episode_requires_reset(tmp_path):
    with pytest.raises(RobotEvalOpsError):
        MockAdapter().run_episode(MockScriptedController(SPECS["mock_scripted_a"]), tmp_path, 30, 2)
