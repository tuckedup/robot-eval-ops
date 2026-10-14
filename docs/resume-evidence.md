# Resume evidence

Only completed, measured work. Each bullet links to the artifact that supports it. Do not edit numbers without
re-running the linked command. Everything below is simulation/software; **no robot hardware was operated.**

## Bullets backed by evidence (two, measured; simulation/software only)

1. **Evaluation and failure analysis in simulation.** Built a paired robot-evaluation pipeline (persisted trial
   lifecycle, physics-evidence scoring, QA that fails closed) and used it for a pre-specified stress study of two scripted
   pick-and-place controllers: protocol piloted on separate seeds, frozen by hash, then 464 held-out trials with 407 verified
   successes and 57 failures categorised from simulator evidence, each linked to its video; the two controllers had different
   failure envelopes (one fails at a 2 kg block, the other when the target is tightened to 35 mm). Reanalysed an earlier
   100-trial run correctly: 50 pairs are 11 distinct start scenarios, B 25.9% shorter in simulated time (95% interval
   24.4-27.4%). Evidence: `docs/stress-study/results_stress_v1/report.md`, `docs/analysis/paired_duration_full_sim/analysis.md`.
   *(Panda in PyBullet, scripted controllers; not a real-robot, throughput or learned-policy result.)*

2. **Data-integrity checks for robot recordings.** Wrote LeRobot v2.1/v3 dataset QA (finite state/action, timestamp and
   index continuity across shards, per-camera decode and frame alignment, actual episode ids) and ran it on a public SO-101
   dataset (`lerobot/svla_so101_pickplace`, Apache-2.0, 50 episodes, 11,939 frames, 2 AV1 cameras: 50/50 accepted, with
   a revision-pinned provenance record); a NaN injected into a copy is rejected for exactly that episode; corrupted trial
   recordings are rejected and cannot count as successes, and an interrupted run recovers without a false success.
   Evidence: `docs/real-data/svla_so101_pickplace/`, `docs/demo/operator/`, `docs/audit-remediation.md`.
   *(The demonstrations were collected by others; no robot hardware was operated.)*

Do not use "built and teleoperated an SO-101" or any hardware sentence unless it is independently true. Agent-team
construction is how the software was built, not a robotics credential.

## Future hardware bullets (placeholders — do NOT use until measured)

- Collected `[N]` teleoperated SO-101 demonstrations across `[3]` sessions; `[X]%` passed demonstration QA
  (evidence: `[manifest + QA report path]`).
- Evaluated `[checkpoint]` on SO-101 over `[N]` supervised trials: `[k/n]` autonomous success, `[m]` interventions,
  Wilson interval `[lo, hi]` (evidence: `[session id + report path]`).
- Independent scoring agreement `[kappa / %]` across `[N]` trials by `[2]` scorers (evidence: `docs/templates/scoring-agreement.csv`
  filled by humans); reset time `[before → after]` over `[N]` resets (evidence: `docs/templates/reset-time-log.csv`).
