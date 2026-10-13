# RobotEvalOps summary

> **MOCK FIXTURE — not evidence of robotics performance**

- Sessions: `756be1cb-4488-4d2e-867c-bc9aa9b9c3db`
- Provenance: mock; controller types: scripted
- Generated: 2026-10-13T17:25:00.569331+00:00

## Results (planned / attempted / completed / failed / aborted / unscored)

| scope | planned | attempted | completed | failed | aborted | unscored | evaluable | success/attempted | success/evaluable |
|---|---|---|---|---|---|---|---|---|---|
| ALL | 4 | 3 | 0 | 3 | 0 | 3 | 0 | 0.000 (0/3) [0.000, 0.562] | n/a (n=0) |

## By controller and condition

| controller | type | provenance | condition | planned | attempted | completed | failed | aborted | unscored | evaluable | success/attempted | success/evaluable | intervention rate | infra-abort rate | recording pass rate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| mock_scripted_a | scripted | mock | mock_state_shift | 2 | 1 | 0 | 1 | 0 | 1 | 0 | 0.000 (0/1) [0.000, 0.793] | n/a (n=0) | 0.000 (0/1) [0.000, 0.793] | 1.000 (1/1) [0.207, 1.000] | 0.000 (0/1) [0.000, 0.793] |
| mock_scripted_a | scripted | mock | nominal | 2 | 2 | 0 | 2 | 0 | 2 | 0 | 0.000 (0/2) [0.000, 0.658] | n/a (n=0) | 0.000 (0/2) [0.000, 0.658] | 1.000 (2/2) [0.342, 1.000] | 0.000 (0/2) [0.000, 0.658] |

## Durations (recorded values only)

trial duration: n=3 recorded value(s) only; nothing imputed. 95th percentile not reported (needs n >= 20).
reset duration: n=3 recorded value(s) only; nothing imputed. 95th percentile not reported (needs n >= 20).

## Paired comparison

Fewer than two controllers: no paired comparison.

## Failure categories

| class | trials |
|---|---|
| infra_failure | 3 |
| not_attempted | 1 |

Every trial appears in exactly one row. infra/abort trials stay unscored and are never counted as task failures; task failures are completed trials scored failure.

## QA and artifact completeness

- artifact completeness: 0.333 (3/9) [0.121, 0.646] (expected 9, missing 6)
- checksums: verified 3, mismatch 0, unverified 0; agreement 1.000 (3/3) [0.438, 1.000]
- recording quality pass rate: 0.000 (0/3) [0.000, 0.562]

## Warnings

- [overall] 1 of 4 planned trial(s) were never attempted; the run is incomplete and rates use the stated denominators.
- [overall] 3 attempted trial(s) are unscored (infra/abort or awaiting scoring).
- [overall] small n: 0 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [overall] 6 expected artifact(s) missing/pending/failed.
- [controller_id=mock_scripted_a, controller_version=1, controller_type=scripted, provenance=mock, condition=mock_state_shift] 1 of 2 planned trial(s) were never attempted; the run is incomplete and rates use the stated denominators.
- [controller_id=mock_scripted_a, controller_version=1, controller_type=scripted, provenance=mock, condition=mock_state_shift] 1 attempted trial(s) are unscored (infra/abort or awaiting scoring).
- [controller_id=mock_scripted_a, controller_version=1, controller_type=scripted, provenance=mock, condition=mock_state_shift] small n: 0 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=mock_scripted_a, controller_version=1, controller_type=scripted, provenance=mock, condition=mock_state_shift] 2 expected artifact(s) missing/pending/failed.
- [controller_id=mock_scripted_a, controller_version=1, controller_type=scripted, provenance=mock, condition=nominal] 2 attempted trial(s) are unscored (infra/abort or awaiting scoring).
- [controller_id=mock_scripted_a, controller_version=1, controller_type=scripted, provenance=mock, condition=nominal] small n: 0 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=mock_scripted_a, controller_version=1, controller_type=scripted, provenance=mock, condition=nominal] 4 expected artifact(s) missing/pending/failed.

## Limitations

- The controllers evaluated by this repository are scripted, state-based programs reading simulator state; they are not learned policies and not trained checkpoints.
- Simulation results use a PyBullet Panda arm with rendered simulator frames. This is not the SO-101 arm and not physical hardware; no conclusion about real-robot performance follows.
- Mock-provenance results are seeded fixtures and are never evidence of robotics performance.
- Visual-only conditions (lighting, background, occlusion) do not change what a state-based controller reads; they say nothing about the visual robustness of a learned policy.
- Small sample sizes: Wilson intervals are wide and any difference between controllers is descriptive. p-values from so few discordant pairs do not support significance claims.
- Scoring agreement between independent human scorers and reset-time improvements are not measured by this report; they need independent human measurement (see docs/evaluation-protocol.md).

## Data sources

- session `756be1cb-4488-4d2e-867c-bc9aa9b9c3db` (demo-eval_smoke_mock-fault-injection-1791912297): run dir `runs/756be1cb-4488-4d2e-867c-bc9aa9b9c3db`, manifest `runs/756be1cb-4488-4d2e-867c-bc9aa9b9c3db/manifest.json` (present), eval_config_hash `12352b3fa1d5646c8126038ca25126f125bcdc9607bf1fd03d12e5cbd29da746`
