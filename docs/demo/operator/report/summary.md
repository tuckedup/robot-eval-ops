# RobotEvalOps summary

> SIMULATION — PyBullet Panda arm with rendered simulator frames; not the SO-101 and not hardware

- Sessions: `e6d57044-b88c-40e8-8112-2e61a63d672a`
- Provenance: simulation; controller types: scripted
- Generated: 2026-10-14T08:45:29.603745+00:00

## Results (planned / attempted / completed / failed / aborted / unscored)

| scope | planned | attempted | completed | failed | aborted | unscored | evaluable | success/attempted | success/evaluable |
|---|---|---|---|---|---|---|---|---|---|
| ALL | 4 | 4 | 4 | 0 | 0 | 0 | 4 | 0.750 (3/4) [0.301, 0.954] | 0.750 (3/4) [0.301, 0.954] |

## By controller and condition

| controller | type | provenance | condition | planned | attempted | completed | failed | aborted | unscored | evaluable | success/attempted | success/evaluable | intervention rate | infra-abort rate | recording pass rate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scripted_baseline_a | scripted | simulation | mass_2.0kg | 1 | 1 | 1 | 0 | 0 | 0 | 1 | 1.000 (1/1) [0.207, 1.000] | 1.000 (1/1) [0.207, 1.000] | 0.000 (0/1) [0.000, 0.793] | 0.000 (0/1) [0.000, 0.793] | 1.000 (1/1) [0.207, 1.000] |
| scripted_baseline_a | scripted | simulation | stress_nominal | 1 | 1 | 1 | 0 | 0 | 0 | 1 | 1.000 (1/1) [0.207, 1.000] | 1.000 (1/1) [0.207, 1.000] | 0.000 (0/1) [0.000, 0.793] | 0.000 (0/1) [0.000, 0.793] | 1.000 (1/1) [0.207, 1.000] |
| scripted_baseline_b | scripted | simulation | mass_2.0kg | 1 | 1 | 1 | 0 | 0 | 0 | 1 | 0.000 (0/1) [0.000, 0.793] | 0.000 (0/1) [0.000, 0.793] | 0.000 (0/1) [0.000, 0.793] | 0.000 (0/1) [0.000, 0.793] | 1.000 (1/1) [0.207, 1.000] |
| scripted_baseline_b | scripted | simulation | stress_nominal | 1 | 1 | 1 | 0 | 0 | 0 | 1 | 1.000 (1/1) [0.207, 1.000] | 1.000 (1/1) [0.207, 1.000] | 0.000 (0/1) [0.000, 0.793] | 0.000 (0/1) [0.000, 0.793] | 1.000 (1/1) [0.207, 1.000] |

## Durations (recorded values only)

trial duration: n=4 recorded value(s) only; nothing imputed. 95th percentile not reported (needs n >= 20).
reset duration: n=4 recorded value(s) only; nothing imputed. 95th percentile not reported (needs n >= 20).

## Paired comparison

### scripted_baseline_a vs scripted_baseline_b

| condition | pairs | both | A only | B only | neither | A success | B success | exact McNemar p |
|---|---|---|---|---|---|---|---|---|
| ALL | 2 | 1 | 1 | 0 | 0 | 1.000 (2/2) [0.342, 1.000] | 0.500 (1/2) [0.095, 0.905] | 1.0000 |
| mass_2.0kg | 1 | 0 | 1 | 0 | 0 | 1.000 (1/1) [0.207, 1.000] | 0.000 (0/1) [0.000, 0.793] | 1.0000 |
| stress_nominal | 1 | 1 | 0 | 0 | 0 | 1.000 (1/1) [0.207, 1.000] | 1.000 (1/1) [0.207, 1.000] | n/a |

The exact McNemar p-value uses only discordant pairs. With the small n typical here it does not support significance claims: it assumes independent pairs, a fixed paired design, and a pre-specified test, and ignores multiple comparisons across conditions. Treat differences as descriptive.

## Failure categories

| class | trials |
|---|---|
| autonomous_success | 3 |
| task_failure | 1 |

Every trial appears in exactly one row. infra/abort trials stay unscored and are never counted as task failures; task failures are completed trials scored failure.

## QA and artifact completeness

- artifact completeness: 1.000 (12/12) [0.757, 1.000] (expected 12, missing 0)
- checksums: verified 12, mismatch 0, unverified 0; agreement 1.000 (12/12) [0.757, 1.000]
- recording quality pass rate: 1.000 (4/4) [0.510, 1.000]

## Warnings

- [overall] small n: 4 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=mass_2.0kg] small n: 1 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=stress_nominal] small n: 1 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=mass_2.0kg] small n: 1 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=stress_nominal] small n: 1 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.

## Limitations

- The controllers evaluated by this repository are scripted, state-based programs reading simulator state; they are not learned policies and not trained checkpoints.
- Simulation results use a PyBullet Panda arm with rendered simulator frames. This is not the SO-101 arm and not physical hardware; no conclusion about real-robot performance follows.
- Mock-provenance results are seeded fixtures and are never evidence of robotics performance.
- Visual-only conditions (lighting, background, occlusion) do not change what a state-based controller reads; they say nothing about the visual robustness of a learned policy.
- Small sample sizes: Wilson intervals are wide and any difference between controllers is descriptive. p-values from so few discordant pairs do not support significance claims.
- Scoring agreement between independent human scorers and reset-time improvements are not measured by this report; they need independent human measurement (see docs/evaluation-protocol.md).

## Data sources

- session `e6d57044-b88c-40e8-8112-2e61a63d672a` (operator-demo-main): run dir `runs/e6d57044-b88c-40e8-8112-2e61a63d672a`, manifest `runs/e6d57044-b88c-40e8-8112-2e61a63d672a/manifest.json` (present), eval_config_hash `d020fb00de9649560bb2bf641a00f83820ffd959216dd1b8f739cfe1fbbe60f6`
