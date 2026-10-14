# Paired duration analysis: scripted_baseline_a vs scripted_baseline_b

> **SIMULATED seconds, scripted controllers, Panda arm in PyBullet. Not robot throughput, not reset time.**

50 trial pairs collapse to **11 distinct start scenarios** (1 scenario(s) replayed identically by several trials). Inference uses the 11 scenarios, not 50.

## Result

- Scenario-weighted mean duration: A 13.150 s, B 9.745 s; paired difference (A-B) **3.405 s** (95% bootstrap interval 3.195 to 3.623, 11 scenarios).
- Relative change of B vs A: **-25.9%** (95% interval -27.4% to -24.4%).
- B was faster in 11 scenarios, slower in 0, tied in 0 (exact sign test p = 0.0009766; descriptive: the 11 scenarios are a bounded perturbation set, not a random sample of a population).
- Trial-weighted (what a raw table shows): A 13.033 s, B 9.593 s, -26.4% change over 50 pairs. This weights the replayed nominal scenario many times; it is reported only so the difference is visible.

## By condition

| condition | pairs | distinct scenarios | mean A (s) | mean B (s) | A-B (s) | sd A | sd B |
|---|---:|---:|---:|---:|---:|---:|---:|
| background | 10 | 1 | 13.000 | 9.550 | 3.450 | 0.000 | 0.000 |
| lighting | 10 | 1 | 13.000 | 9.550 | 3.450 | 0.000 | 0.000 |
| nominal | 10 | 1 | 13.000 | 9.550 | 3.450 | 0.000 | 0.000 |
| object_position | 10 | 10 | 13.165 | 9.765 | 3.400 | 0.418 | 0.351 |
| occlusion | 10 | 1 | 13.000 | 9.550 | 3.450 | 0.000 | 0.000 |

sd = 0 means every trial in that condition replayed the same physical scenario bit-for-bit.

## What the speed costs (paired, scenario-weighted)

| quantity | A | B | A-B | 95% interval of A-B | B larger / A larger / tie |
|---|---:|---:|---:|---|---|
| max_contact_normal_force_n (N) | 40.04 | 24 | 16.04 | 16.04 to 16.05 | 0 / 11 / 0 |
| final_distance_to_target_center_m (m) | 0.01591 | 0.01782 | -0.001907 | -0.00337 to -0.0004904 | 7 / 4 / 0 |
| block_final_speed_mps (m/s) | 2.653e-05 | 1.237e-05 | 1.416e-05 | -6.457e-09 to 2.834e-05 | 8 / 3 / 0 |
| max_block_height_m (m) | 0.2198 | 0.2797 | -0.05994 | -0.05994 to -0.05994 | 11 / 0 / 0 |

## Where the time goes (one nominal trial per controller, from recorded actions)

| controller | approach (s) | carry (s) | release + dwell (s) | trace length (s) |
|---|---:|---:|---:|---:|
| scripted_baseline_a | 3.70 | 7.10 | 2.60 | 13.40 |
| scripted_baseline_b | 2.50 | 4.90 | 1.90 | 9.30 |

## Controller parameters (the treatments)

- **scripted_baseline_a**: `{"config_hash": "a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7", "descend_speed": 0.08, "grasp_z": 0.02, "grip_force": 20.0, "hover_z": 0.2, "joint_speed_limit": 1.2, "lift_z": 0.22, "move_speed": 0.2}`
- **scripted_baseline_b**: `{"close_settle_steps": 6, "config_hash": "2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6", "descend_speed": 0.15, "grasp_z": 0.02, "grip_force": 12.0, "hover_z": 0.28, "joint_speed_limit": 1.6, "lift_z": 0.28, "move_speed": 0.35}`

## Limits

- Durations are SIMULATED seconds (PyBullet Panda, 20 Hz control). They are not robot throughput, reset time, or any real-world measurement; the arm is a Panda, not an SO-101.
- Deterministic replay: lighting/background/occlusion only change rendered pixels that these state-based scripted controllers never read, and the nominal start is fixed. Those trials replay one physical scenario, so they are collapsed before inference. Trial counts overstate the evidence.
- Inference units are distinct start scenarios (a bounded +-4 cm perturbation around one nominal pose). Intervals describe that start distribution in this simulator only; they do not generalise to other objects, friction, masses, delays or a real arm.
- Both controllers succeeded on every trial, so duration is the only discriminating outcome here. A faster controller is not shown to be better: see the trade-off table (contact force, placement accuracy, final block speed) and the failure study for what the speed costs.
- Both durations include a fixed 2.0 s placement dwell, so the relative saving in ACTIVE time is larger than the relative saving in total time.
