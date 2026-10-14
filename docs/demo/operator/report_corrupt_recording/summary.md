# RobotEvalOps summary

> SIMULATION — PyBullet Panda arm with rendered simulator frames; not the SO-101 and not hardware

- Sessions: `95a17e99-453a-4ac3-ba88-e8f3267e1665`
- Provenance: simulation; controller types: scripted
- Generated: 2026-10-14T08:45:29.985760+00:00

## Results (planned / attempted / completed / failed / aborted / unscored)

| scope | planned | attempted | completed | failed | aborted | unscored | evaluable | success/attempted | success/evaluable |
|---|---|---|---|---|---|---|---|---|---|
| ALL | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0.000 (0/1) [0.000, 0.793] | n/a (n=0) |

## By controller and condition

| controller | type | provenance | condition | planned | attempted | completed | failed | aborted | unscored | evaluable | success/attempted | success/evaluable | intervention rate | infra-abort rate | recording pass rate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scripted_baseline_a | scripted | simulation | stress_nominal | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0.000 (0/1) [0.000, 0.793] | n/a (n=0) | 0.000 (0/1) [0.000, 0.793] | 0.000 (0/1) [0.000, 0.793] | 0.000 (0/1) [0.000, 0.793] |

## Durations (recorded values only)

trial duration: n=1 recorded value(s) only; nothing imputed. 95th percentile not reported (needs n >= 20).
reset duration: n=1 recorded value(s) only; nothing imputed. 95th percentile not reported (needs n >= 20).

## Paired comparison

Fewer than two controllers: no paired comparison.

## Failure categories

| class | trials |
|---|---|
| non_autonomous_success | 1 |

Every trial appears in exactly one row. infra/abort trials stay unscored and are never counted as task failures; task failures are completed trials scored failure.

## QA and artifact completeness

- artifact completeness: 1.000 (3/3) [0.438, 1.000] (expected 3, missing 0)
- checksums: verified 0, mismatch 0, unverified 3; agreement n/a (n=0)
- recording quality pass rate: 0.000 (0/1) [0.000, 0.793]

## Warnings

- [overall] small n: 0 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [overall] 1 scored trial(s) excluded from 'evaluable' because recording QA is not accepted (fail/error/unchecked); 0 of the 1 raw task success(es) are unverified (shown, not hidden).
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=stress_nominal] small n: 0 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=stress_nominal] 1 scored trial(s) excluded from 'evaluable' because recording QA is not accepted (fail/error/unchecked); 0 of the 1 raw task success(es) are unverified (shown, not hidden).

## Limitations

- The controllers evaluated by this repository are scripted, state-based programs reading simulator state; they are not learned policies and not trained checkpoints.
- Simulation results use a PyBullet Panda arm with rendered simulator frames. This is not the SO-101 arm and not physical hardware; no conclusion about real-robot performance follows.
- Mock-provenance results are seeded fixtures and are never evidence of robotics performance.
- Visual-only conditions (lighting, background, occlusion) do not change what a state-based controller reads; they say nothing about the visual robustness of a learned policy.
- Small sample sizes: Wilson intervals are wide and any difference between controllers is descriptive. p-values from so few discordant pairs do not support significance claims.
- Scoring agreement between independent human scorers and reset-time improvements are not measured by this report; they need independent human measurement (see docs/evaluation-protocol.md).

## Data sources

- session `95a17e99-453a-4ac3-ba88-e8f3267e1665` (operator-demo-corrupt): run dir `runs/95a17e99-453a-4ac3-ba88-e8f3267e1665`, manifest `runs/95a17e99-453a-4ac3-ba88-e8f3267e1665/manifest.json` (present), eval_config_hash `061a1a644330fb6cc0dee37bbb5e7ecbba03faf340d9a706bcdeb19a38400830`
