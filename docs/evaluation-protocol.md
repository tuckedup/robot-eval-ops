# Evaluation protocol

Status: protocol definition. It describes how trials are defined, scored and reported. It contains no measured
results; measured values live in generated reports (`report export`) and `docs/verification.md`, each linked to the
session that produced them.

## 1. Task and scoring rubric (`rubric-v1`)

Task `pick_place_block_v1`: pick the block and place it in the target region.

A trial is a **success** only if ALL hold within the 30 s attempt timeout:

0. the block was **picked, not pushed** (a verified grasp and lift, see below);
1. the block is **entirely** inside the target region: every corner strictly inside; touching the boundary does
   not count;
2. the block has been **released** (gripper open / no longer held);
3. conditions 1 and 2 **stay true for 2 s** (dwell) without the block moving out.

Otherwise the completed trial is a **failure** (timeout, dropped block, outside the region, not released). A
block that was pushed or dragged into the region without a verified grasp and lift is a **task failure**, not a
success.

**Simulation evidence rule (rubric-v1).** In simulation the grasp+lift is verified from recorded state: bilateral
finger contact on the block for at least a minimum number of steps AND the block lifted at least 0.03 m at some
point. The evidence fields are `grasped`, `lift_m` and `both_finger_contact_steps`. Success then also needs the
release and the 2.0 s dwell with the block entirely inside the target. **Hardware and imported recordings** are
scored from the video: the operator checks that the block was picked up and not pushed, plus the criteria above.

- **Operator assistance prevents an autonomous success.** Any touch of the block or scene, repositioning, retry,
  hand-guiding or help that changes the outcome sets `intervention = assisted`. The outcome may still be recorded as
  success, but it is counted as an assisted success, never as an autonomous one. If the scorer cannot tell,
  `intervention = unknown`, which also never counts as autonomous.
- Scoring is independent of lifecycle. Infrastructure, recording or preflight failures and aborted attempts are
  `FAILED`/`ABORTED` and stay `unscored`; they are never turned into task failures or successes.
- Only `COMPLETED` trials can be scored. A first score uses `report score`; a change uses `report edit-score` with a
  mandatory reason and is kept in an audit log.
- Simulator and mock trials are scored by the Runner from recorded state (`physics_evidence` / `mock_fixture`).
  Hardware and imported recordings are scored by a human from the video (`operator_video` / `imported_label`).
- The full rubric text and scorer instructions are in `docs/templates/scoring-rubric.md` (versioned).

## 2. Provenance versus controller type

| Field | Values | Meaning |
|---|---|---|
| provenance | `mock`, `simulation`, `imported_real_recording`, `physical_hardware` | where the data came from |
| controller type | `scripted`, `learned`, `teleoperated` | who produced the actions |

They are independent. A scripted config is not a learned checkpoint. Mock output is a fixture and is never evidence
of robotics performance. The simulator is a PyBullet Panda arm, not the SO-101. Reports always show both fields and
a banner for mock data (`MOCK FIXTURE — not evidence of robotics performance`).

## 3. Denominators (single definition, `docs/contracts.md` section 5)

| Term | Definition |
|---|---|
| planned | every trial in the session(s); never-attempted trials stay here |
| attempted | `started_at` set (the trial reached RUNNING) |
| completed / failed / aborted | lifecycle state counts |
| unscored | attempted with `task_outcome = unscored` |
| evaluable | COMPLETED, scored success or failure, and `recording_quality != fail` |
| autonomous success rate (per attempt) | autonomous successes / attempted |
| autonomous success rate (per evaluable) | autonomous successes / evaluable |
| intervention rate | `intervention = assisted` / attempted |
| infra-abort rate | attempted trials ended by infra reasons (`infra_failure`, `recording_failure`, `preflight_failed`, `interrupted_runner`) / attempted |
| recording-quality pass rate | `recording_quality = pass` / attempted |
| artifact completeness | present-with-hash artifacts / expected (expected = every registered artifact of an attempted trial plus a video and a trace for each attempted trial) |
| checksum agreement | verified / transferred (uploaded + verified + mismatch) |

Autonomous success = COMPLETED, scored success, `intervention = none`, non-teleoperated controller, recording quality
not `fail`. Both success rates are reported with a Wilson 95% interval; with n = 0 the rate is "n/a", never 0 or 1.
Quality exclusions and incomplete runs are shown in the results table (planned/attempted/completed/failed/aborted/
unscored), not hidden.

Durations (trial and reset) use recorded values only: mean, median, min, max and n. A 95th percentile is only
reported when n >= 20. Missing durations are never imputed.

## 4. Conditions and pairing

Conditions are bounded and versioned (`configs/conditions/*.yaml`): `nominal`, `object_position`, `lighting`,
`background`, `occlusion`. Only `object_position` changes simulator state read by a state-based controller
(`affects_controller_state: true`); lighting, background and occlusion are visual-only, so a scripted state-based
controller is expected to be unaffected. That says nothing about the visual robustness of a learned policy.

Pairing: the seed depends only on `(base_seed, condition, trial_index)`, so every controller faces the same seed in
the same cell. The paired comparison reports per-condition success for each controller, discordant counts (A only,
B only, both, neither) and an exact two-sided McNemar (binomial) p-value. Unpaired or non-evaluable partners are
listed, never dropped. With the sample sizes here, p-values do not support significance claims; treat differences as
descriptive.

## 5. Full template and smoke runs

- **Full simulation template** (`configs/eval_full_sim.yaml`): 2 controllers x 5 conditions x 10 trials = **100
  planned trials**, provenance `simulation` (Panda).
- **Smoke runs** (`configs/eval_smoke_mock.yaml`, `configs/eval_smoke_sim.yaml`): small plumbing checks. Mock smoke
  runs test software only; neither smoke run is a performance measurement.
- A run that stops early still reports all 100 planned trials; the unattempted ones remain visible as `planned`.

## 6. Targets versus measured

`configs/targets.yaml` holds **proposed targets only** (for example 100 evaluation trials, 10 fault cases, 100%
checksum agreement). They are goals, not results. Measured values appear only in generated reports and
`docs/verification.md`, with the session id, config hash and manifest path that produced them. A report never copies
a target into a result.

## 7. What needs independent human measurement

These are listed under `needs_independent_human_measurement` in `configs/targets.yaml` and are not produced by
software alone:

- **Scoring agreement**: two humans score the same videos independently (blind to each other); record them in
  `docs/templates/scoring-agreement.csv`, then run `report agreement`. Percent agreement and Cohen's kappa are
  computed only from those rows.
- **Reset-time improvement**: a person times scene resets with a stopwatch before and after a procedure change,
  recorded in `docs/templates/reset-time-log.csv`. Software-recorded `reset_duration_s` is an optional extra, not a
  substitute.
- Real-hardware success rates, which exist only if a session with provenance `physical_hardware` actually ran.

## 8. Reporting checklist

Every report states: sessions and run ids; provenance and controller type; config hashes and seeds; the
planned/attempted/completed/failed/aborted/unscored row; denominators; Wilson intervals; warnings for small n and
missing data; failures by category; QA and artifact completeness; and limitations (scripted state-based controller
not learned; sim is Panda, not SO-101; mock is not evidence; small n).
