"""Streamlit dashboard (read/score only; NO physical controls). Run:

    streamlit run src/robotevalops/dashboard/app.py

Data home: sidebar field, default $ROBOTEVALOPS_HOME or ./data. All data comes from EvalService.
"""

from __future__ import annotations

import os

import streamlit as st

from robotevalops import scoring
from robotevalops.core.service import EvalService
from robotevalops.dashboard import views
from robotevalops.errors import RobotEvalOpsError
from robotevalops.schemas import Intervention, TaskOutcome
from robotevalops.util import get_home


def _scoring_panel(svc: EvalService, session_id: str, trial_id: str) -> None:
    t = svc.get_trial(trial_id)
    st.caption(
        f"current score: {t.task_outcome.value} (source {t.score_source.value}), "
        f"intervention {t.intervention.value}, rubric {t.rubric_version}"
    )
    st.dataframe(views.score_history_frame(svc, trial_id), use_container_width=True)
    scorer = st.text_input("Scorer / editor name (required)", key=f"who_{trial_id}")
    outcome = st.radio("Outcome (rubric-v1)", ["success", "failure"], horizontal=True, key=f"out_{trial_id}")
    interv = st.radio("Operator intervention", ["none", "assisted"], horizontal=True, key=f"int_{trial_id}")
    unscored = t.task_outcome == TaskOutcome.UNSCORED
    reason = "" if unscored else st.text_input("Reason for edit (required)", key=f"why_{trial_id}")
    label = "Apply first score" if unscored else "Edit score (audited)"
    if st.button(label, key=f"btn_{trial_id}"):
        try:
            if unscored:
                scoring.apply_score(
                    svc, trial_id, TaskOutcome(outcome), scorer=scorer, intervention=Intervention(interv)
                )
            else:
                scoring.edit_score(
                    svc,
                    trial_id,
                    TaskOutcome(outcome),
                    editor=scorer,
                    reason=reason,
                    intervention=Intervention(interv),
                )
            st.success("score recorded")
        except (RobotEvalOpsError, ValueError) as e:
            st.error(str(e))


def main() -> None:
    st.set_page_config(page_title="RobotEvalOps dashboard", layout="wide")
    st.title("RobotEvalOps dashboard")
    st.caption("Read and score only. This dashboard has no robot controls.")
    home = st.sidebar.text_input(
        "Data home (ROBOTEVALOPS_HOME)", value=str(get_home(os.environ.get("ROBOTEVALOPS_HOME")))
    )
    svc = EvalService(home)
    sessions = views.session_table(svc)
    st.subheader("Sessions")
    if sessions.empty:
        st.info(f"No sessions found in {svc.home}. Create one with `robotevalops session create`.")
        return
    st.dataframe(sessions, use_container_width=True)
    sid = st.sidebar.selectbox("Session", sessions["session_id"].tolist())
    bundle = views.load_bundles(svc, [sid])[0]
    for b in views.session_banners(bundle):
        if "MOCK" in b:
            st.error(b)
        else:
            st.warning(b)

    for w in views.unchecked_warnings(views.metrics_for(svc, [sid])):
        st.warning(w)

    tabs = st.tabs(
        ["Trials", "Metrics", "Condition comparison", "Failures", "Artifact QA", "Video and logs", "Scoring"]
    )
    trials_df = views.trial_table(svc, sid)
    with tabs[0]:
        c1, c2, c3 = st.columns(3)
        ctl = c1.selectbox("Controller", [""] + sorted(trials_df["controller_id"].unique().tolist()))
        cond = c2.selectbox("Condition", [""] + sorted(trials_df["condition"].unique().tolist()))
        stt = c3.selectbox("State", [""] + sorted(trials_df["state"].unique().tolist()))
        st.dataframe(
            views.trial_table(svc, sid, controller=ctl or None, condition=cond or None, state=stt or None),
            use_container_width=True,
        )
    with tabs[1]:
        rep = views.metrics_for(svc, [sid])
        if rep.banner:
            st.error(rep.banner)
        st.dataframe(views.metrics_frame(rep), use_container_width=True)
        for w in rep.warnings + [w for g in rep.by_controller_condition for w in g.warnings]:
            st.warning(w)
    with tabs[2]:
        ctrls = sorted(trials_df["controller_id"].unique().tolist())
        if len(ctrls) < 2:
            st.info("Need at least two controllers for a paired comparison.")
        else:
            a = st.selectbox("Controller A", ctrls, index=0)
            bb = st.selectbox("Controller B", ctrls, index=1)
            cmp, df = views.condition_comparison(svc, [sid], a, bb)
            st.dataframe(df, use_container_width=True)
            st.warning(cmp.caveat)
            if cmp.unpaired:
                st.write("Not analysed as pairs:")
                st.dataframe([u.model_dump() for u in cmp.unpaired])
    with tabs[3]:
        frep, fdf = views.failure_frame(svc, [sid])
        st.dataframe(fdf, use_container_width=True)
        st.json({"class_totals": frep.class_totals, "qa_flag_counts": frep.qa_flag_counts})
    with tabs[4]:
        st.dataframe(views.qa_frame(svc, sid), use_container_width=True)
    ids = trials_df["trial_id"].tolist()
    with tabs[5]:
        tid = st.selectbox("Trial", ids, key="viewer_trial")
        trial = views.get_trial_in_session(svc, sid, tid)
        path, msg = views.resolve_trial_video(svc, trial)
        if path is None:
            st.error(msg)
        else:
            st.video(str(path))
        st.dataframe(views.artifact_frame(trial), use_container_width=True)
        lines, lmsg = views.read_trial_log(svc, trial)
        if lmsg:
            st.warning(lmsg)
        else:
            st.code("\n".join(lines))
    with tabs[6]:
        tid2 = st.selectbox("Trial to score", ids, key="score_trial")
        _scoring_panel(svc, sid, tid2)


main()
