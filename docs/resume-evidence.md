# Resume evidence

Only completed, measured work. Each bullet links to the artifact that supports it. Do not edit numbers without
re-running the linked command. Everything below is simulation/software; **no robot hardware was operated.**

## Bullets backed by evidence

1. **Built a reproducible robot-evaluation pipeline and ran a 100-trial PyBullet Panda pick-and-place study**
   (2 versioned scripted controllers × 5 conditions × 10 paired seeds): outcomes derived from recorded physics state
   (grasp contact, lift, containment, release, 2 s dwell), 100/100 trials recorded with video + state/action traces,
   100/100 recording-QA pass, and 300/300 artifacts SHA-256-verified after a local-store round trip. Every trial stays in the
   denominators; rates carry Wilson 95% intervals.
   Evidence: `docs/demo/sim-full-100/summary.md` · `docs/verification.md` §4 · command
   `robotevalops demo run --backend sim --config src/robotevalops/configs/eval_full_sim.yaml`.
   *(Scripted state-based controllers in simulation: not a learned-policy or real-world result.)*

2. **Designed a ten-case fault-injection and data-QA suite** (missing/truncated video, non-monotonic timestamps, NaN
   actions, wrong schema, missing model artifact, duplicate IDs, hash mismatch, transfer timeout, interrupted runner):
   10/10 detected with actionable errors, source evidence preserved, and no fault able to end as a success; backed by a
   745-test suite (ruff + mypy clean; 578 offline + 53 physics re-run in a clean clone) and a clean-clone reproduction.
   Evidence: `docs/fault-injection-report.md` · `docs/verification.md` §3, §6.

3. **Ran a multi-agent build with an independent adversarial verifier**: four specialist engineer agents plus a
   verifier who did not write the code; it found 19 defects (1 blocker, 5 major, including a QA-to-metrics wiring gap and a
   success rule that accepted pushed blocks). All were fixed and turned into regression tests.
   Evidence: `docs/verification-findings.md` · `docs/implementation-status.md` · `.claude/agents/`.

## Future hardware bullets (placeholders — do NOT use until measured)

- Collected `[N]` teleoperated SO-101 demonstrations across `[3]` sessions; `[X]%` passed demonstration QA
  (evidence: `[manifest + QA report path]`).
- Evaluated `[checkpoint]` on SO-101 over `[N]` supervised trials: `[k/n]` autonomous success, `[m]` interventions,
  Wilson interval `[lo, hi]` (evidence: `[session id + report path]`).
- Independent scoring agreement `[kappa / %]` across `[N]` trials by `[2]` scorers (evidence: `docs/templates/scoring-agreement.csv`
  filled by humans); reset time `[before → after]` over `[N]` resets (evidence: `docs/templates/reset-time-log.csv`).
