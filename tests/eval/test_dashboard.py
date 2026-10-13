from __future__ import annotations

from pathlib import Path

import pytest

from robotevalops.dashboard import views
from robotevalops.schemas import ArtifactRef, ArtifactRole, ArtifactStatus, Provenance


def test_session_and_trial_tables(seeded):
    svc, sess = seeded
    sdf = views.session_table(svc)
    assert len(sdf) == 1 and sdf.iloc[0]["planned_trials"] == 12
    tdf = views.trial_table(svc, sess.session_id)
    assert len(tdf) == 12
    assert len(views.trial_table(svc, sess.session_id, controller="ctrl1", state="planned")) == 1
    empty = views.session_table(type(svc)(svc.home / "other"))
    assert empty.empty and list(empty.columns) == views.SESSION_COLUMNS


def test_metrics_comparison_failures_frames(seeded):
    svc, sess = seeded
    rep = views.metrics_for(svc, [sess.session_id])
    mf = views.metrics_frame(rep)
    assert mf["planned"].sum() == 12 and set(mf["controller_type"]) == {"scripted"}
    cmp, df = views.condition_comparison(svc, [sess.session_id], "ctrl0", "ctrl1")
    assert "A only" in df.columns and cmp.caveat
    frep, fdf = views.failure_frame(svc, [sess.session_id])
    assert fdf["count"].sum() == 12 and frep.total_trials == 12


def test_banners():
    assert any("MOCK FIXTURE" in b for b in views.banners(["mock"]))
    assert any("Panda" in b for b in views.banners(["simulation"]))


def test_video_resolution_safe(seeded):
    svc, sess = seeded
    trials = svc.list_trials(sess.session_id)
    with_video = next(t for t in trials if t.artifacts)
    path, msg = views.resolve_trial_video(svc, with_video)
    assert path is not None and path.name == "video.mp4" and msg == ""
    path.unlink()
    path2, msg2 = views.resolve_trial_video(svc, with_video)
    assert path2 is None and "missing artifact" in msg2
    # no artifact registered and no file: explicit message too
    infra = next(t for t in trials if t.state.value == "failed")
    p3, m3 = views.resolve_trial_video(svc, infra)
    assert p3 is None and "missing artifact" in m3


@pytest.mark.parametrize("evil", ["../../../etc/passwd", "/abs/video.mp4", "trials/../../x.mp4", r"..\x.mp4"])
def test_video_traversal_rejected(seeded, evil):
    svc, sess = seeded
    t = next(t for t in svc.list_trials(sess.session_id) if t.artifacts)
    bad = t.model_copy(
        update={
            "artifacts": [ArtifactRef(role=ArtifactRole.VIDEO, relpath=evil, status=ArtifactStatus.PRESENT)]
        }
    )
    path, msg = views.resolve_trial_video(svc, bad)
    assert path is None and "refused unsafe artifact path" in msg


def test_symlink_escape_rejected(seeded, tmp_path):
    svc, sess = seeded
    t = next(t for t in svc.list_trials(sess.session_id) if t.artifacts)
    outside = tmp_path / "secret.mp4"
    outside.write_bytes(b"x")
    link = svc.trial_dir(sess.session_id, t.trial_id) / "link.mp4"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this platform")
    bad = t.model_copy(
        update={
            "artifacts": [
                ArtifactRef(
                    role=ArtifactRole.VIDEO,
                    relpath=f"trials/{t.trial_id}/link.mp4",
                    status=ArtifactStatus.PRESENT,
                )
            ]
        }
    )
    path, msg = views.resolve_trial_video(svc, bad)
    assert path is None and "unsafe" in msg


def test_log_missing_message_and_read(seeded):
    svc, sess = seeded
    t = svc.list_trials(sess.session_id)[0]
    lines, msg = views.read_trial_log(svc, t)
    assert lines == [] and "missing artifact" in msg
    (svc.trial_dir(sess.session_id, t.trial_id) / "trial.log.jsonl").write_text("a\nb\nc\n", encoding="utf-8")
    lines, msg = views.read_trial_log(svc, t, max_lines=2)
    assert lines == ["b", "c"] and msg == ""


def test_app_runs_headless_with_appTest(seeded, monkeypatch):
    from streamlit.testing.v1 import AppTest

    svc, sess = seeded
    monkeypatch.setenv("ROBOTEVALOPS_HOME", str(svc.home))
    app = Path(views.__file__).with_name("app.py")
    at = AppTest.from_file(str(app), default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Panda" in w.value for w in at.warning)  # provenance banner
    assert len(at.tabs) >= 7
    assert at.title[0].value == "RobotEvalOps dashboard"


def test_app_mock_banner_and_empty_home(svc, monkeypatch, tmp_path):
    from eval_seed import seed_session
    from streamlit.testing.v1 import AppTest

    s = seed_session(svc, Provenance.MOCK, "mockdash")
    monkeypatch.setenv("ROBOTEVALOPS_HOME", str(svc.home))
    app = Path(views.__file__).with_name("app.py")
    at = AppTest.from_file(str(app), default_timeout=60).run()
    assert not at.exception
    assert any("MOCK FIXTURE" in e.value for e in at.error)
    assert s.session_id

    monkeypatch.setenv("ROBOTEVALOPS_HOME", str(tmp_path / "empty"))
    at2 = AppTest.from_file(str(app), default_timeout=60).run()
    assert not at2.exception and any("No sessions" in i.value for i in at2.info)


def test_dashboard_unchecked_column_and_warning(seeded):
    svc, sess = seeded
    from robotevalops.schemas import RecordingQuality

    df = views.trial_table(svc, sess.session_id)
    assert "recording_qa_status" in df.columns
    t = next(t for t in svc.list_trials(sess.session_id) if t.is_attempted)
    svc.set_recording_quality(t.trial_id, RecordingQuality.UNCHECKED)
    df = views.trial_table(svc, sess.session_id)
    assert (df["recording_qa_status"] == "no QA result (unchecked)").any()
    ws = views.unchecked_warnings(views.metrics_for(svc, [sess.session_id]))
    assert len(ws) == 1 and "data validate" in ws[0]
