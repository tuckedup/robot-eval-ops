# RobotEvalOps summary

> SIMULATION — PyBullet Panda arm with rendered simulator frames; not the SO-101 and not hardware

- Sessions: `693a7a68-beb1-4f74-af00-48ef65824482`
- Provenance: simulation; controller types: scripted
- Generated: 2026-10-13T17:48:14.898106+00:00

## Results (planned / attempted / completed / failed / aborted / unscored)

| scope | planned | attempted | completed | failed | aborted | unscored | evaluable | success/attempted | success/evaluable |
|---|---|---|---|---|---|---|---|---|---|
| ALL | 100 | 100 | 100 | 0 | 0 | 0 | 100 | 1.000 (100/100) [0.963, 1.000] | 1.000 (100/100) [0.963, 1.000] |

## By controller and condition

| controller | type | provenance | condition | planned | attempted | completed | failed | aborted | unscored | evaluable | success/attempted | success/evaluable | intervention rate | infra-abort rate | recording pass rate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scripted_baseline_a | scripted | simulation | background | 10 | 10 | 10 | 0 | 0 | 0 | 10 | 1.000 (10/10) [0.722, 1.000] | 1.000 (10/10) [0.722, 1.000] | 0.000 (0/10) [0.000, 0.278] | 0.000 (0/10) [0.000, 0.278] | 1.000 (10/10) [0.722, 1.000] |
| scripted_baseline_a | scripted | simulation | lighting | 10 | 10 | 10 | 0 | 0 | 0 | 10 | 1.000 (10/10) [0.722, 1.000] | 1.000 (10/10) [0.722, 1.000] | 0.000 (0/10) [0.000, 0.278] | 0.000 (0/10) [0.000, 0.278] | 1.000 (10/10) [0.722, 1.000] |
| scripted_baseline_a | scripted | simulation | nominal | 10 | 10 | 10 | 0 | 0 | 0 | 10 | 1.000 (10/10) [0.722, 1.000] | 1.000 (10/10) [0.722, 1.000] | 0.000 (0/10) [0.000, 0.278] | 0.000 (0/10) [0.000, 0.278] | 1.000 (10/10) [0.722, 1.000] |
| scripted_baseline_a | scripted | simulation | object_position | 10 | 10 | 10 | 0 | 0 | 0 | 10 | 1.000 (10/10) [0.722, 1.000] | 1.000 (10/10) [0.722, 1.000] | 0.000 (0/10) [0.000, 0.278] | 0.000 (0/10) [0.000, 0.278] | 1.000 (10/10) [0.722, 1.000] |
| scripted_baseline_a | scripted | simulation | occlusion | 10 | 10 | 10 | 0 | 0 | 0 | 10 | 1.000 (10/10) [0.722, 1.000] | 1.000 (10/10) [0.722, 1.000] | 0.000 (0/10) [0.000, 0.278] | 0.000 (0/10) [0.000, 0.278] | 1.000 (10/10) [0.722, 1.000] |
| scripted_baseline_b | scripted | simulation | background | 10 | 10 | 10 | 0 | 0 | 0 | 10 | 1.000 (10/10) [0.722, 1.000] | 1.000 (10/10) [0.722, 1.000] | 0.000 (0/10) [0.000, 0.278] | 0.000 (0/10) [0.000, 0.278] | 1.000 (10/10) [0.722, 1.000] |
| scripted_baseline_b | scripted | simulation | lighting | 10 | 10 | 10 | 0 | 0 | 0 | 10 | 1.000 (10/10) [0.722, 1.000] | 1.000 (10/10) [0.722, 1.000] | 0.000 (0/10) [0.000, 0.278] | 0.000 (0/10) [0.000, 0.278] | 1.000 (10/10) [0.722, 1.000] |
| scripted_baseline_b | scripted | simulation | nominal | 10 | 10 | 10 | 0 | 0 | 0 | 10 | 1.000 (10/10) [0.722, 1.000] | 1.000 (10/10) [0.722, 1.000] | 0.000 (0/10) [0.000, 0.278] | 0.000 (0/10) [0.000, 0.278] | 1.000 (10/10) [0.722, 1.000] |
| scripted_baseline_b | scripted | simulation | object_position | 10 | 10 | 10 | 0 | 0 | 0 | 10 | 1.000 (10/10) [0.722, 1.000] | 1.000 (10/10) [0.722, 1.000] | 0.000 (0/10) [0.000, 0.278] | 0.000 (0/10) [0.000, 0.278] | 1.000 (10/10) [0.722, 1.000] |
| scripted_baseline_b | scripted | simulation | occlusion | 10 | 10 | 10 | 0 | 0 | 0 | 10 | 1.000 (10/10) [0.722, 1.000] | 1.000 (10/10) [0.722, 1.000] | 0.000 (0/10) [0.000, 0.278] | 0.000 (0/10) [0.000, 0.278] | 1.000 (10/10) [0.722, 1.000] |

## Durations (recorded values only)

trial duration: n=100 recorded value(s) only; nothing imputed.
reset duration: n=100 recorded value(s) only; nothing imputed.

## Paired comparison

### scripted_baseline_a vs scripted_baseline_b

| condition | pairs | both | A only | B only | neither | A success | B success | exact McNemar p |
|---|---|---|---|---|---|---|---|---|
| ALL | 50 | 50 | 0 | 0 | 0 | 1.000 (50/50) [0.929, 1.000] | 1.000 (50/50) [0.929, 1.000] | n/a |
| background | 10 | 10 | 0 | 0 | 0 | 1.000 (10/10) [0.722, 1.000] | 1.000 (10/10) [0.722, 1.000] | n/a |
| lighting | 10 | 10 | 0 | 0 | 0 | 1.000 (10/10) [0.722, 1.000] | 1.000 (10/10) [0.722, 1.000] | n/a |
| nominal | 10 | 10 | 0 | 0 | 0 | 1.000 (10/10) [0.722, 1.000] | 1.000 (10/10) [0.722, 1.000] | n/a |
| object_position | 10 | 10 | 0 | 0 | 0 | 1.000 (10/10) [0.722, 1.000] | 1.000 (10/10) [0.722, 1.000] | n/a |
| occlusion | 10 | 10 | 0 | 0 | 0 | 1.000 (10/10) [0.722, 1.000] | 1.000 (10/10) [0.722, 1.000] | n/a |

The exact McNemar p-value uses only discordant pairs. With the small n typical here it does not support significance claims: it assumes independent pairs, a fixed paired design, and a pre-specified test, and ignores multiple comparisons across conditions. Treat differences as descriptive.

## Failure categories

| class | trials |
|---|---|
| autonomous_success | 100 |

Every trial appears in exactly one row. infra/abort trials stay unscored and are never counted as task failures; task failures are completed trials scored failure.

## QA and artifact completeness

- artifact completeness: 1.000 (300/300) [0.987, 1.000] (expected 300, missing 0)
- checksums: verified 300, mismatch 0, unverified 0; agreement 1.000 (300/300) [0.987, 1.000]
- recording quality pass rate: 1.000 (100/100) [0.963, 1.000]

## Warnings

- [controller_id=scripted_baseline_a, controller_version=1, controller_type=scripted, provenance=simulation, condition=background] small n: 10 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_type=scripted, provenance=simulation, condition=lighting] small n: 10 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_type=scripted, provenance=simulation, condition=nominal] small n: 10 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_type=scripted, provenance=simulation, condition=object_position] small n: 10 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_type=scripted, provenance=simulation, condition=occlusion] small n: 10 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_type=scripted, provenance=simulation, condition=background] small n: 10 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_type=scripted, provenance=simulation, condition=lighting] small n: 10 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_type=scripted, provenance=simulation, condition=nominal] small n: 10 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_type=scripted, provenance=simulation, condition=object_position] small n: 10 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_type=scripted, provenance=simulation, condition=occlusion] small n: 10 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.

## Limitations

- The controllers evaluated by this repository are scripted, state-based programs reading simulator state; they are not learned policies and not trained checkpoints.
- Simulation results use a PyBullet Panda arm with rendered simulator frames. This is not the SO-101 arm and not physical hardware; no conclusion about real-robot performance follows.
- Mock-provenance results are seeded fixtures and are never evidence of robotics performance.
- Visual-only conditions (lighting, background, occlusion) do not change what a state-based controller reads; they say nothing about the visual robustness of a learned policy.
- Small sample sizes: Wilson intervals are wide and any difference between controllers is descriptive. p-values from so few discordant pairs do not support significance claims.
- Scoring agreement between independent human scorers and reset-time improvements are not measured by this report; they need independent human measurement (see docs/evaluation-protocol.md).

## Data sources

- session `693a7a68-beb1-4f74-af00-48ef65824482` (demo-eval_full_sim-1791912285): run dir `runs/693a7a68-beb1-4f74-af00-48ef65824482`, manifest `runs/693a7a68-beb1-4f74-af00-48ef65824482/manifest.json` (present), eval_config_hash `18a858462eb8d9d31bbcc0b4d98f1801917faf5c4d39fceab0ba12f8efece28d`
