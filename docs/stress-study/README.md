# Physics stress study (`stress_v1`)

A pre-specified, failure-oriented study of the two scripted controllers on the simulated Panda pick-and-place.
**Simulation only, scripted (not learned) controllers.** It exists because the original 100-trial acceptance run
had 100/100 successes and 60 of those trials changed only pixels a state-based controller never reads, so it
could not discriminate between controllers on robustness.

## Procedure (enforced by `robotevalops study ...`)

1. **Bounded factors** (`src/robotevalops/configs/conditions/sim_stress_conditions.yaml`, hard-clamped in
   `adapters/sim_pybullet.py:STRESS_BOUNDS`): block mass, block friction, block size, block yaw, tighter target,
   actuation delay, observation noise, plus two combined conditions. Each condition also keeps the seeded +-4 cm
   start offset, so seeds mean different physical starts. No success flag is ever set by the harness: success
   comes from simulator evidence (`all corners inside`, released, dwell, >=5 consecutive bilateral-contact steps,
   lift).
2. **Pilot** (`study pilot`, seeds from base seed 9001, 1 trial per cell): feasibility only. Checks that every
   cell runs to completion, applied parameters equal requested ones (nothing clamped) and evidence is readable.
   Pilot results are never reported. Pilot: 58/58 completed, 7 task failures, no problems.
3. **Freeze** (`study freeze`): writes `protocol_stress_v1.frozen.json` with SHA-256 of the protocol, the
   conditions file and the controllers file, the git commit, and the pilot summary. A frozen protocol is never
   re-frozen.
4. **Held-out evaluation** (`study run`, base seed 52000, 8 seeds per cell, 29 cells x 2 controllers = 464
   trials). It refuses to start if any of the three files changed since freezing, or if the derived pilot and
   evaluation seed sets overlap (they do not: checked by `check_seeds_disjoint` and a test).
5. **Report** (`study report`): every attempted trial is in the denominator; failures are categorised from
   recorded evidence only (`grasp_failed`, `lift_failed`, `dropped_in_transit`, `placement_outside_target`,
   `release_failed`, `dwell_not_held`, `infra_failure`, `unverified_recording`) and each carries trial id,
   session, video and trace paths.

No trial is dropped, re-seeded or re-labelled after results are seen.

## Reproduce

```bash
robotevalops study pilot  --home data/stress_pilot --workers 8
robotevalops study freeze --pilot-home data/stress_pilot
robotevalops study run    --home data/stress_eval  --workers 8
robotevalops study report --home data/stress_eval  --out docs/stress-study/results_stress_v1
```

Results: `docs/stress-study/results_stress_v1/report.md` (+ `results.json`, `failure_envelope.png`).
Raw runs and videos stay under `data/stress_eval/runs/<session>/trials/<trial>/` (gitignored).

## Limits

Eight seeds per cell is small and the intervals are wide; a factor level is a physical stress inside this
simulator, not a real-world prior; nothing here says anything about an SO-101 or a learned policy.
