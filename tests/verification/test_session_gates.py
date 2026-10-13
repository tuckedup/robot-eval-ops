# ruff: noqa: E501, B023
"""V2b: session-level illegal transitions, planning abuse, hostile artifact paths via the public service."""

from __future__ import annotations

from pathlib import Path

import pytest

from robotevalops.adapters.mock import MockAdapter
from robotevalops.controllers.mock_scripted import MockScriptedController
from robotevalops.core.runner import Runner
from robotevalops.core.service import EvalService
from robotevalops.dashboard.views import resolve_trial_video
from robotevalops.errors import (
    DuplicateIdError,
    InvalidTransitionError,
    PathTraversalError,
    PreflightFailedError,
)
from robotevalops.schemas import (
    ArtifactRef,
    ArtifactRole,
    ConditionSpec,
    ControllerSpec,
    ControllerType,
    EvalConfig,
    Provenance,
    SessionState,
    TrialState,
)


def _cfg(trials: int = 2) -> EvalConfig:
    return EvalConfig(
        name="g",
        provenance=Provenance.MOCK,
        backend="mock",
        controllers=[ControllerSpec(controller_id="c", type=ControllerType.SCRIPTED, version="1")],
        conditions=[ConditionSpec(name="k", kind="nominal")],
        trials_per_condition=trials,
    )


def _mk(tmp_path: Path):
    svc = EvalService(tmp_path / "home")
    cfg = _cfg()
    s = svc.create_session("g", Provenance.MOCK, "mock", eval_config=cfg)
    svc.plan_trials(s.session_id, cfg)
    return svc, s.session_id, cfg


@pytest.mark.parametrize(
    "new", [SessionState.RUNNING, SessionState.COMPLETED, SessionState.FAILED, SessionState.READY]
)
def test_planned_session_cannot_jump(tmp_path: Path, new) -> None:
    svc, sid, _ = _mk(tmp_path)
    with pytest.raises(InvalidTransitionError):
        svc.transition_session(sid, new)


def test_terminal_session_is_frozen(tmp_path: Path) -> None:
    svc, sid, _ = _mk(tmp_path)
    svc.transition_session(sid, SessionState.ABORTED)
    for st in SessionState:
        with pytest.raises(InvalidTransitionError):
            svc.transition_session(sid, st)
    with pytest.raises(InvalidTransitionError):
        svc.mark_preflight_passed(sid)
    with pytest.raises(InvalidTransitionError):
        svc.acknowledge_operator(sid, "x")


def test_replanning_or_planning_after_start_is_refused_and_trials_survive(tmp_path: Path) -> None:
    svc, sid, cfg = _mk(tmp_path)
    ids = [t.trial_id for t in svc.list_trials(sid)]
    with pytest.raises((InvalidTransitionError, DuplicateIdError)):
        svc.plan_trials(sid, cfg)
    svc.mark_preflight_passed(sid)
    with pytest.raises(InvalidTransitionError):
        svc.plan_trials(sid, cfg)
    assert [t.trial_id for t in svc.list_trials(sid)] == ids


def test_flag_survives_manual_ready_transition_and_runner_still_refuses(tmp_path: Path) -> None:
    svc, sid, _ = _mk(tmp_path)
    runner = Runner(svc, lambda s: MockAdapter(), lambda spec: MockScriptedController(spec))
    svc.transition_session(sid, SessionState.PREFLIGHT)
    svc.transition_session(sid, SessionState.READY)
    svc.transition_session(sid, SessionState.RUNNING)
    svc.transition_session(sid, SessionState.PREFLIGHT)  # recovery edge sets the flag
    assert svc.get_session(sid).requires_fresh_preflight is True
    svc.transition_session(sid, SessionState.READY)  # trying to skip the preflight by hand
    assert svc.get_session(sid).requires_fresh_preflight is True
    with pytest.raises(PreflightFailedError):
        runner.run_session(sid)
    assert all(t.state == TrialState.PLANNED for t in svc.list_trials(sid))


def test_stop_request_is_idempotent_and_prevents_any_trial(tmp_path: Path) -> None:
    svc, sid, _ = _mk(tmp_path)
    assert svc.request_stop(sid) is True and svc.request_stop(sid) is False
    rep = Runner(svc, lambda s: MockAdapter(), lambda spec: MockScriptedController(spec)).run_session(sid)
    assert rep.stopped and rep.trials_processed == []
    assert all(t.state == TrialState.PLANNED for t in svc.list_trials(sid))  # planned trials remain visible
    assert svc.get_session(sid).state == SessionState.ABORTED


@pytest.mark.parametrize(
    "rel", ["../x", "/etc/passwd", "a/../../b", "C:\\x", "a\\b", ".aws/credentials", "x/.env", "a//b"]
)
def test_register_artifacts_rejects_hostile_relpaths(tmp_path: Path, rel: str) -> None:
    svc, sid, _ = _mk(tmp_path)
    t = svc.list_trials(sid)[0]
    with pytest.raises(PathTraversalError):
        svc.register_artifacts(t.trial_id, [ArtifactRef(role=ArtifactRole.VIDEO, relpath=rel)])
    assert svc.get_trial(t.trial_id).artifacts == []


def test_dashboard_video_resolver_refuses_traversal_even_if_db_has_hostile_path(tmp_path: Path) -> None:
    """Simulate a tampered DB row (bypassing the service) holding a traversal path."""
    import json
    import sqlite3

    svc, sid, _ = _mk(tmp_path)
    t = svc.list_trials(sid)[0]
    (tmp_path / "home" / "secret.mp4").write_bytes(b"x")
    con = sqlite3.connect(svc.home / "robotevalops.db")
    con.execute(
        "UPDATE trials SET artifacts_json=? WHERE trial_id=?",
        (json.dumps([{"role": "video", "relpath": "../../secret.mp4", "status": "present"}]), t.trial_id),
    )
    con.commit()
    con.close()
    path, msg = resolve_trial_video(svc, svc.get_trial(t.trial_id))
    assert path is None and "unsafe" in msg
