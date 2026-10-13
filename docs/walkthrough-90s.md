# 90-second walkthrough (script)

**0:00 — Problem.** "Robot teams lose time to untracked tests: which checkpoint, which scene, did it really
succeed, was a human helping, did the recording survive the transfer? RobotEvalOps makes that boring and auditable."

**0:15 — Run.** `robotevalops demo run` plans a paired schedule (same seeds for both controllers), runs each trial
through a persisted lifecycle (planned → preflight → ready → running → completed/failed/aborted) and records video +
state/action traces. Default backend is a *mock fixture* — labelled everywhere, never performance evidence.
`--backend sim` runs a real PyBullet Panda pick-and-place; success comes from recorded physics evidence
(block fully in target, released, 2 s dwell inside a 30 s attempt), nothing teleported or random.

**0:40 — Honest accounting.** Failed, aborted, interrupted and unscored trials stay in the denominators. Assisted
runs never count as autonomous success. Rates use Wilson 95% intervals and say when n is too small.

**0:55 — Data QA + faults.** Ten deterministic fault cases (missing/truncated video, bad timestamps, NaN actions,
wrong schema, missing model, duplicate id, hash mismatch, transfer timeout, interrupted runner) are each detected,
evidence is preserved, and none can end as a success.

**1:10 — Artifacts + hardware.** Artifacts round-trip through a local store (or user-owned S3) with SHA-256
verification. An SO-101/LeRobot pathway exists but refuses to move anything without hardware mode, per-session
operator acknowledgement and a passing preflight; it has only been tested with fake executables.

**1:25 — Close.** `streamlit run src/robotevalops/dashboard/app.py` browses sessions, trials, failures, videos and
the scoring audit trail. What's not done: real hardware runs, a learned policy, real-AWS verification.
