# RobotEvalOps summary

> **MOCK FIXTURE — not evidence of robotics performance**

- Sessions: `ff0a25f0-fa05-4342-ad08-53d87b72f7cc`
- Provenance: mock; controller types: scripted
- Generated: 2026-10-13T17:24:59.807223+00:00

## Results (planned / attempted / completed / failed / aborted / unscored)

| scope | planned | attempted | completed | failed | aborted | unscored | evaluable | success/attempted | success/evaluable |
|---|---|---|---|---|---|---|---|---|---|
| ALL | 12 | 12 | 12 | 0 | 0 | 0 | 12 | 0.750 (9/12) [0.468, 0.911] | 0.750 (9/12) [0.468, 0.911] |

## By controller and condition

| controller | type | provenance | condition | planned | attempted | completed | failed | aborted | unscored | evaluable | success/attempted | success/evaluable | intervention rate | infra-abort rate | recording pass rate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| mock_scripted_a | scripted | mock | mock_state_shift | 2 | 2 | 2 | 0 | 0 | 0 | 2 | 0.500 (1/2) [0.095, 0.905] | 0.500 (1/2) [0.095, 0.905] | 0.000 (0/2) [0.000, 0.658] | 0.000 (0/2) [0.000, 0.658] | 1.000 (2/2) [0.342, 1.000] |
| mock_scripted_a | scripted | mock | mock_visual_shift | 2 | 2 | 2 | 0 | 0 | 0 | 2 | 1.000 (2/2) [0.342, 1.000] | 1.000 (2/2) [0.342, 1.000] | 0.000 (0/2) [0.000, 0.658] | 0.000 (0/2) [0.000, 0.658] | 1.000 (2/2) [0.342, 1.000] |
| mock_scripted_a | scripted | mock | nominal | 2 | 2 | 2 | 0 | 0 | 0 | 2 | 1.000 (2/2) [0.342, 1.000] | 1.000 (2/2) [0.342, 1.000] | 0.000 (0/2) [0.000, 0.658] | 0.000 (0/2) [0.000, 0.658] | 1.000 (2/2) [0.342, 1.000] |
| mock_scripted_b | scripted | mock | mock_state_shift | 2 | 2 | 2 | 0 | 0 | 0 | 2 | 1.000 (2/2) [0.342, 1.000] | 1.000 (2/2) [0.342, 1.000] | 0.000 (0/2) [0.000, 0.658] | 0.000 (0/2) [0.000, 0.658] | 1.000 (2/2) [0.342, 1.000] |
| mock_scripted_b | scripted | mock | mock_visual_shift | 2 | 2 | 2 | 0 | 0 | 0 | 2 | 0.500 (1/2) [0.095, 0.905] | 0.500 (1/2) [0.095, 0.905] | 0.000 (0/2) [0.000, 0.658] | 0.000 (0/2) [0.000, 0.658] | 1.000 (2/2) [0.342, 1.000] |
| mock_scripted_b | scripted | mock | nominal | 2 | 2 | 2 | 0 | 0 | 0 | 2 | 0.500 (1/2) [0.095, 0.905] | 0.500 (1/2) [0.095, 0.905] | 0.000 (0/2) [0.000, 0.658] | 0.000 (0/2) [0.000, 0.658] | 1.000 (2/2) [0.342, 1.000] |

## Durations (recorded values only)

trial duration: n=12 recorded value(s) only; nothing imputed. 95th percentile not reported (needs n >= 20).
reset duration: n=12 recorded value(s) only; nothing imputed. 95th percentile not reported (needs n >= 20).

## Paired comparison

### mock_scripted_a vs mock_scripted_b

| condition | pairs | both | A only | B only | neither | A success | B success | exact McNemar p |
|---|---|---|---|---|---|---|---|---|
| ALL | 6 | 3 | 2 | 1 | 0 | 0.833 (5/6) [0.436, 0.970] | 0.667 (4/6) [0.300, 0.903] | 1.0000 |
| mock_state_shift | 2 | 1 | 0 | 1 | 0 | 0.500 (1/2) [0.095, 0.905] | 1.000 (2/2) [0.342, 1.000] | 1.0000 |
| mock_visual_shift | 2 | 1 | 1 | 0 | 0 | 1.000 (2/2) [0.342, 1.000] | 0.500 (1/2) [0.095, 0.905] | 1.0000 |
| nominal | 2 | 1 | 1 | 0 | 0 | 1.000 (2/2) [0.342, 1.000] | 0.500 (1/2) [0.095, 0.905] | 1.0000 |

The exact McNemar p-value uses only discordant pairs. With the small n typical here it does not support significance claims: it assumes independent pairs, a fixed paired design, and a pre-specified test, and ignores multiple comparisons across conditions. Treat differences as descriptive.

## Failure categories

| class | trials |
|---|---|
| autonomous_success | 9 |
| task_failure | 3 |

Every trial appears in exactly one row. infra/abort trials stay unscored and are never counted as task failures; task failures are completed trials scored failure.

## QA and artifact completeness

- artifact completeness: 1.000 (36/36) [0.904, 1.000] (expected 36, missing 0)
- checksums: verified 36, mismatch 0, unverified 0; agreement 1.000 (36/36) [0.904, 1.000]
- recording quality pass rate: 1.000 (12/12) [0.757, 1.000]

## Warnings

- [overall] small n: 12 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=mock_scripted_a, controller_version=1, controller_type=scripted, provenance=mock, condition=mock_state_shift] small n: 2 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=mock_scripted_a, controller_version=1, controller_type=scripted, provenance=mock, condition=mock_visual_shift] small n: 2 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=mock_scripted_a, controller_version=1, controller_type=scripted, provenance=mock, condition=nominal] small n: 2 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=mock_scripted_b, controller_version=1, controller_type=scripted, provenance=mock, condition=mock_state_shift] small n: 2 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=mock_scripted_b, controller_version=1, controller_type=scripted, provenance=mock, condition=mock_visual_shift] small n: 2 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=mock_scripted_b, controller_version=1, controller_type=scripted, provenance=mock, condition=nominal] small n: 2 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.

## Limitations

- The controllers evaluated by this repository are scripted, state-based programs reading simulator state; they are not learned policies and not trained checkpoints.
- Simulation results use a PyBullet Panda arm with rendered simulator frames. This is not the SO-101 arm and not physical hardware; no conclusion about real-robot performance follows.
- Mock-provenance results are seeded fixtures and are never evidence of robotics performance.
- Visual-only conditions (lighting, background, occlusion) do not change what a state-based controller reads; they say nothing about the visual robustness of a learned policy.
- Small sample sizes: Wilson intervals are wide and any difference between controllers is descriptive. p-values from so few discordant pairs do not support significance claims.
- Scoring agreement between independent human scorers and reset-time improvements are not measured by this report; they need independent human measurement (see docs/evaluation-protocol.md).

## Data sources

- session `ff0a25f0-fa05-4342-ad08-53d87b72f7cc` (demo-eval_smoke_mock-1791912294): run dir `runs/ff0a25f0-fa05-4342-ad08-53d87b72f7cc`, manifest `runs/ff0a25f0-fa05-4342-ad08-53d87b72f7cc/manifest.json` (present), eval_config_hash `22d912f28c224876b4e6bd3181cfacd74bdbf6422246f6a01f3cb9df7cbb34d8`
