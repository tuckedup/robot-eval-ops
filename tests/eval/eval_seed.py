"""Seed an EvalService home with hand-specified trial outcomes (NO simulated metrics; outcomes are explicit
test inputs). 2 controllers x 2 conditions x 3 trials = 12 planned trials."""

from __future__ import annotations

from pathlib import Path

from robotevalops.core.service import EvalService
from robotevalops.schemas import (
    ArtifactRef,
    ArtifactRole,
    ArtifactStatus,
    ConditionSpec,
    ControllerSpec,
    ControllerType,
    EvalConfig,
    Intervention,
    Provenance,
    RecordingQuality,
    ScoreSource,
    SessionRecord,
    TaskOutcome,
    TerminationReason,
    TrialState,
)

VIDEO = b"not-a-real-video-test-bytes"

# (controller, condition, index) -> behaviour
PLAN = {
    ("ctrl0", "cond1", 2): "failure",
    ("ctrl1", "cond0", 0): "infra",
    ("ctrl1", "cond0", 1): "abort",
    ("ctrl1", "cond0", 2): "assisted",
    ("ctrl1", "cond1", 0): "unscored_completed",
    ("ctrl1", "cond1", 1): "failure",
    ("ctrl1", "cond1", 2): "never",
}


def make_eval_config(provenance: Provenance = Provenance.SIMULATION) -> EvalConfig:
    return EvalConfig(
        name="eval-test",
        provenance=provenance,
        backend="mock" if provenance == Provenance.MOCK else "pybullet_panda",
        controllers=[
            ControllerSpec(
                controller_id=f"ctrl{i}", type=ControllerType.SCRIPTED, version="1", config={"k": i}
            )
            for i in range(2)
        ],
        conditions=[ConditionSpec(name=f"cond{i}", kind="nominal") for i in range(2)],
        trials_per_condition=3,
        base_seed=11,
    )


def seed_session(
    svc: EvalService, provenance: Provenance = Provenance.SIMULATION, name: str = "seeded"
) -> SessionRecord:
    cfg = make_eval_config(provenance)
    sess = svc.create_session(name, provenance, cfg.backend, eval_config=cfg)
    trials = svc.plan_trials(sess.session_id, cfg)
    assert len(trials) == 12
    for t in trials:
        beh = PLAN.get((t.controller_id, t.condition_name, t.trial_index), "success")
        if beh == "never":
            continue
        svc.transition_trial(t.trial_id, TrialState.PREFLIGHT)
        svc.transition_trial(t.trial_id, TrialState.READY)
        svc.transition_trial(t.trial_id, TrialState.RUNNING)
        tdir = svc.trial_dir(sess.session_id, t.trial_id)
        tdir.mkdir(parents=True, exist_ok=True)
        if beh == "infra":
            svc.record_trial_result(
                t.trial_id, termination_reason=TerminationReason.INFRA_FAILURE, duration_s=None
            )
            continue
        if beh == "abort":
            svc.record_trial_result(
                t.trial_id, termination_reason=TerminationReason.OPERATOR_ABORT, duration_s=0.5
            )
            continue
        (tdir / "video.mp4").write_bytes(VIDEO)
        art = [
            ArtifactRef(
                role=ArtifactRole.VIDEO,
                relpath=f"trials/{t.trial_id}/video.mp4",
                sha256="ab" * 32,
                size_bytes=len(VIDEO),
                status=ArtifactStatus.PRESENT,
            )
        ]
        win = beh in ("success", "assisted")
        scored = beh != "unscored_completed"
        svc.record_trial_result(
            t.trial_id,
            termination_reason=TerminationReason.SUCCESS_CRITERION_MET if win else TerminationReason.TIMEOUT,
            duration_s=3.0 + t.trial_index if win else 30.0,
            task_outcome=(TaskOutcome.SUCCESS if win else TaskOutcome.FAILURE) if scored else None,
            score_source=ScoreSource.PHYSICS_EVIDENCE if scored else None,
            intervention=Intervention.ASSISTED if beh == "assisted" else Intervention.NONE,
            artifacts=art,
            recording_quality=RecordingQuality.PASS,
        )
    return svc.get_session(sess.session_id)


def video_path(svc: EvalService, session_id: str, trial_id: str) -> Path:
    return svc.trial_dir(session_id, trial_id) / "video.mp4"
