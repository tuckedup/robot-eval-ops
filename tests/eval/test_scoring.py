from __future__ import annotations

import pytest

from robotevalops import scoring
from robotevalops.errors import InvalidTransitionError, RobotEvalOpsError, ScoreProtectionError
from robotevalops.schemas import Intervention, ScoreSource, TaskOutcome, TrialState


def _unscored(svc, sid):
    ts = scoring.list_unscored(svc, sid)
    assert len(ts) == 1  # exactly the seeded completed-unscored trial
    return ts[0]


def test_list_unscored_only_completed(seeded):
    svc, sess = seeded
    t = _unscored(svc, sess.session_id)
    assert t.state == TrialState.COMPLETED and t.task_outcome == TaskOutcome.UNSCORED


def test_apply_score_then_second_score_raises_and_edit_is_audited(seeded):
    svc, sess = seeded
    t = _unscored(svc, sess.session_id)
    out = scoring.apply_score(
        svc, t.trial_id, TaskOutcome.SUCCESS, scorer="alice", intervention=Intervention.NONE
    )
    assert out.task_outcome == TaskOutcome.SUCCESS and out.score_source == ScoreSource.OPERATOR_VIDEO
    assert out.intervention == Intervention.NONE
    events = [e for e in svc.list_events(sess.session_id) if e["kind"] == "score_rubric"]
    assert events[-1]["detail"]["rubric_version"] == "rubric-v1" and events[-1]["detail"]["scorer"] == "alice"
    with pytest.raises(ScoreProtectionError):
        scoring.apply_score(
            svc, t.trial_id, TaskOutcome.FAILURE, scorer="bob", intervention=Intervention.NONE
        )
    with pytest.raises(ValueError, match="reason"):
        scoring.edit_score(
            svc, t.trial_id, TaskOutcome.FAILURE, editor="bob", reason="  ", intervention=Intervention.NONE
        )
    edit = scoring.edit_score(
        svc,
        t.trial_id,
        TaskOutcome.FAILURE,
        editor="bob",
        reason="block released outside target on re-watch",
        intervention=Intervention.ASSISTED,
    )
    assert edit.before_outcome == TaskOutcome.SUCCESS and edit.after_outcome == TaskOutcome.FAILURE
    hist = scoring.score_history(svc, t.trial_id)
    assert len(hist) == 1 and hist[0].editor == "bob" and "re-watch" in hist[0].reason
    assert svc.get_trial(t.trial_id).task_outcome == TaskOutcome.FAILURE


def test_scorer_and_intervention_required(seeded):
    svc, sess = seeded
    t = _unscored(svc, sess.session_id)
    with pytest.raises(ValueError, match="scorer"):
        scoring.apply_score(svc, t.trial_id, TaskOutcome.SUCCESS, scorer=" ", intervention=Intervention.NONE)
    with pytest.raises(ValueError, match="intervention"):
        scoring.apply_score(
            svc, t.trial_id, TaskOutcome.SUCCESS, scorer="a", intervention=Intervention.UNKNOWN
        )
    with pytest.raises(ValueError, match="rubric"):
        scoring.apply_score(
            svc,
            t.trial_id,
            TaskOutcome.SUCCESS,
            scorer="a",
            intervention=Intervention.NONE,
            rubric_version="rubric-v0",
        )
    with pytest.raises(ValueError, match="human"):
        scoring.apply_score(
            svc,
            t.trial_id,
            TaskOutcome.SUCCESS,
            scorer="a",
            intervention=Intervention.NONE,
            source=ScoreSource.MOCK_FIXTURE,
        )
    assert svc.get_trial(t.trial_id).task_outcome == TaskOutcome.UNSCORED  # nothing was written


def test_cannot_score_non_completed(seeded):
    svc, sess = seeded
    aborted = [t for t in svc.list_trials(sess.session_id) if t.state == TrialState.ABORTED][0]
    with pytest.raises(InvalidTransitionError):
        scoring.apply_score(
            svc, aborted.trial_id, TaskOutcome.SUCCESS, scorer="a", intervention=Intervention.NONE
        )


def test_agreement_hand_computed():
    # both S:4, a=S/b=F:1, a=F/b=S:1, both F:4 -> po=0.8, pa(S)=pb(S)=0.5, pe=0.5, kappa=0.6
    a = ["success"] * 5 + ["failure"] * 5
    b = ["success"] * 4 + ["failure"] + ["success"] + ["failure"] * 4
    r = scoring.scoring_agreement(a, b)
    assert (r.n, r.agreements) == (10, 8)
    assert r.percent_agreement == pytest.approx(0.8)
    assert r.expected_agreement == pytest.approx(0.5)
    assert r.cohen_kappa == pytest.approx(0.6)
    assert r.confusion == {
        "failure:failure": 4,
        "failure:success": 1,
        "success:failure": 1,
        "success:success": 4,
    }


def test_agreement_edge_cases():
    e = scoring.scoring_agreement([], [])
    assert e.percent_agreement is None and e.cohen_kappa is None
    same = scoring.scoring_agreement(["success"] * 3, ["success"] * 3)
    assert same.percent_agreement == 1.0 and same.cohen_kappa is None  # pe == 1: undefined
    with pytest.raises(ValueError):
        scoring.scoring_agreement(["success"], [])


def test_load_agreement_csv(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text(
        "trial_id,scorer_a,outcome_a,scorer_b,outcome_b,rubric_version,notes\n"
        "t1,ann,success,bo,success,rubric-v1,\n"
        "t2,ann,failure,bo,success,rubric-v1,\n"
        "t3,ann,failure,bo,,rubric-v1,not yet scored by b\n",
        encoding="utf-8",
    )
    ids, a, b = scoring.load_agreement_csv(p)
    assert ids == ["t1", "t2"]
    assert scoring.agreement_from_csv(p).percent_agreement == 0.5
    p.write_text(
        "trial_id,scorer_a,outcome_a,scorer_b,outcome_b\nt1,ann,success,ann,success\n", encoding="utf-8"
    )
    with pytest.raises(RobotEvalOpsError, match="different"):
        scoring.load_agreement_csv(p)
    p.write_text("trial_id,scorer_a,outcome_a\n", encoding="utf-8")
    with pytest.raises(RobotEvalOpsError, match="missing column"):
        scoring.load_agreement_csv(p)
