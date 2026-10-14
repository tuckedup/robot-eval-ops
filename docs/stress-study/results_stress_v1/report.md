# Physics stress study `stress_v1` (evaluation)

> **SIMULATION ONLY: Panda arm, PyBullet, scripted (not learned) controllers. No claim about a real robot or a learned policy.**

Attempted **464** of 464 planned trials: 407 verified successes, 57 task failures, 0 infra failures, 0 unverified recordings. Every attempted trial is in the denominator; nothing was dropped or re-run.

## Failure categories (from recorded simulator evidence)

- `placement_outside_target`: 48
- `release_failed`: 5
- `dropped_in_transit`: 3
- `lift_failed`: 1

## Failure envelope by controller and factor

Success rate per level (k/n), mildest to most severe; the level column is the applied physical value.

### scripted_baseline_a

| family | levels (value: success) | first < 100% | first < 50% |
|---|---|---|---|
| mass | 0.05: 8/8; 0.2: 8/8; 0.5: 8/8; 1: 8/8; 2: 8/8 | - | - |
| friction | 1: 8/8; 0.6: 8/8; 0.4: 8/8; 0.25: 8/8; 0.15: 7/8 | friction_0.15 | - |
| size | 0.02: 8/8; 0.025: 8/8; 0.03: 8/8; 0.035: 7/8 | half_size_35mm | - |
| yaw | 0: 8/8; 15: 8/8; 30: 8/8; 45: 8/8 | - | - |
| target | 0.06: 8/8; 0.05: 8/8; 0.04: 8/8; 0.035: 2/8; 0.03: 0/8 | target_half_35mm | target_half_35mm |
| delay | 0: 8/8; 1: 8/8; 2: 8/8; 4: 8/8; 8: 8/8 | - | - |
| noise | 0: 8/8; 0.002: 8/8; 0.005: 8/8; 0.01: 8/8; 0.02: 6/8 | obs_noise_20mm | - |

### scripted_baseline_b

| family | levels (value: success) | first < 100% | first < 50% |
|---|---|---|---|
| mass | 0.05: 8/8; 0.2: 8/8; 0.5: 8/8; 1: 8/8; 2: 0/8 | mass_2.0kg | mass_2.0kg |
| friction | 1: 8/8; 0.6: 8/8; 0.4: 8/8; 0.25: 8/8; 0.15: 8/8 | - | - |
| size | 0.02: 8/8; 0.025: 8/8; 0.03: 8/8; 0.035: 7/8 | half_size_35mm | - |
| yaw | 0: 8/8; 15: 8/8; 30: 8/8; 45: 8/8 | - | - |
| target | 0.06: 8/8; 0.05: 8/8; 0.04: 8/8; 0.035: 0/8; 0.03: 0/8 | target_half_35mm | target_half_35mm |
| delay | 0: 8/8; 1: 8/8; 2: 8/8; 4: 8/8; 8: 8/8 | - | - |
| noise | 0: 8/8; 0.002: 8/8; 0.005: 8/8; 0.01: 8/8; 0.02: 5/8 | obs_noise_20mm | - |

## Combined stress

- joint_moderate / scripted_baseline_a: 7/8  categories {'placement_outside_target': 1}
- joint_moderate / scripted_baseline_b: 7/8  categories {'placement_outside_target': 1}
- joint_severe / scripted_baseline_a: 3/8  categories {'placement_outside_target': 5}
- joint_severe / scripted_baseline_b: 4/8  categories {'placement_outside_target': 4}

## Failures with evidence links

| category | condition | controller | trial | seed | offset from target (m) | max contact force (N) | video | trace |
|---|---|---|---|---:|---:|---:|---|---|
| lift_failed | friction_0.15 | scripted_baseline_a | 6 | 1708541971 | 0.493 | 49.2 | `runs/961a5ea6-2d80-4605-91f7-b30639a03f25/trials/4f962814-8c7a-4f4f-aec9-02e9a5b49f4c/video.mp4` | `runs/961a5ea6-2d80-4605-91f7-b30639a03f25/trials/4f962814-8c7a-4f4f-aec9-02e9a5b49f4c/trace.jsonl` |
| placement_outside_target | half_size_35mm | scripted_baseline_a | 2 | 2187471304 | 0.037 | 262.7 | `runs/7194b4e9-049a-40fe-8edb-b8ce0069fd7e/trials/9b2ed160-d74b-47d7-93a7-d921543c2605/video.mp4` | `runs/7194b4e9-049a-40fe-8edb-b8ce0069fd7e/trials/9b2ed160-d74b-47d7-93a7-d921543c2605/trace.jsonl` |
| release_failed | half_size_35mm | scripted_baseline_b | 3 | 4038630901 | 0.001 | 273.4 | `runs/7194b4e9-049a-40fe-8edb-b8ce0069fd7e/trials/d5a4a4b1-deb5-493c-99c6-1d9d042dac9e/video.mp4` | `runs/7194b4e9-049a-40fe-8edb-b8ce0069fd7e/trials/d5a4a4b1-deb5-493c-99c6-1d9d042dac9e/trace.jsonl` |
| placement_outside_target | joint_moderate | scripted_baseline_a | 3 | 4051250718 | 0.012 | 51.2 | `runs/c773b88b-8b85-4700-8b7a-c4b46d5ab613/trials/9fe312c6-e291-4e2f-a2c7-b647dfd72912/video.mp4` | `runs/c773b88b-8b85-4700-8b7a-c4b46d5ab613/trials/9fe312c6-e291-4e2f-a2c7-b647dfd72912/trace.jsonl` |
| placement_outside_target | joint_moderate | scripted_baseline_b | 3 | 4051250718 | 0.015 | 24.0 | `runs/c773b88b-8b85-4700-8b7a-c4b46d5ab613/trials/656c8c90-b8a9-4e04-9359-eab21adc5e24/video.mp4` | `runs/c773b88b-8b85-4700-8b7a-c4b46d5ab613/trials/656c8c90-b8a9-4e04-9359-eab21adc5e24/trace.jsonl` |
| placement_outside_target | joint_severe | scripted_baseline_a | 3 | 2972445533 | 0.017 | 317.3 | `runs/c773b88b-8b85-4700-8b7a-c4b46d5ab613/trials/dbd0dd77-ed00-4859-93f7-41b8722d99b3/video.mp4` | `runs/c773b88b-8b85-4700-8b7a-c4b46d5ab613/trials/dbd0dd77-ed00-4859-93f7-41b8722d99b3/trace.jsonl` |
| placement_outside_target | joint_severe | scripted_baseline_a | 4 | 4172318345 | 0.024 | 320.9 | `runs/c773b88b-8b85-4700-8b7a-c4b46d5ab613/trials/c5f0b4da-b599-409c-9c68-51204abb163c/video.mp4` | `runs/c773b88b-8b85-4700-8b7a-c4b46d5ab613/trials/c5f0b4da-b599-409c-9c68-51204abb163c/trace.jsonl` |
| placement_outside_target | joint_severe | scripted_baseline_a | 5 | 596121027 | 0.012 | 310.2 | `runs/c773b88b-8b85-4700-8b7a-c4b46d5ab613/trials/063e41bc-d278-409f-9e2b-d53ebed28e7a/video.mp4` | `runs/c773b88b-8b85-4700-8b7a-c4b46d5ab613/trials/063e41bc-d278-409f-9e2b-d53ebed28e7a/trace.jsonl` |
| placement_outside_target | joint_severe | scripted_baseline_a | 6 | 133596335 | 0.012 | 307.4 | `runs/c773b88b-8b85-4700-8b7a-c4b46d5ab613/trials/95308272-8e32-4bf3-ac84-2bd2d9fd05cb/video.mp4` | `runs/c773b88b-8b85-4700-8b7a-c4b46d5ab613/trials/95308272-8e32-4bf3-ac84-2bd2d9fd05cb/trace.jsonl` |
| placement_outside_target | joint_severe | scripted_baseline_a | 7 | 556780486 | 0.014 | 265.3 | `runs/c773b88b-8b85-4700-8b7a-c4b46d5ab613/trials/44532488-05ee-4df9-98c0-3cc355fd0f39/video.mp4` | `runs/c773b88b-8b85-4700-8b7a-c4b46d5ab613/trials/44532488-05ee-4df9-98c0-3cc355fd0f39/trace.jsonl` |
| placement_outside_target | joint_severe | scripted_baseline_b | 2 | 142329827 | 0.013 | 287.7 | `runs/c773b88b-8b85-4700-8b7a-c4b46d5ab613/trials/086415c8-af00-4eb6-b470-4a176cf2df0e/video.mp4` | `runs/c773b88b-8b85-4700-8b7a-c4b46d5ab613/trials/086415c8-af00-4eb6-b470-4a176cf2df0e/trace.jsonl` |
| placement_outside_target | joint_severe | scripted_baseline_b | 3 | 2972445533 | 0.016 | 361.0 | `runs/c773b88b-8b85-4700-8b7a-c4b46d5ab613/trials/55aa1f3e-ef1d-4721-bda1-877c305856b7/video.mp4` | `runs/c773b88b-8b85-4700-8b7a-c4b46d5ab613/trials/55aa1f3e-ef1d-4721-bda1-877c305856b7/trace.jsonl` |
| placement_outside_target | joint_severe | scripted_baseline_b | 4 | 4172318345 | 0.012 | 309.2 | `runs/c773b88b-8b85-4700-8b7a-c4b46d5ab613/trials/8a140e00-a427-4e41-a1ca-0de242ccc5c0/video.mp4` | `runs/c773b88b-8b85-4700-8b7a-c4b46d5ab613/trials/8a140e00-a427-4e41-a1ca-0de242ccc5c0/trace.jsonl` |
| placement_outside_target | joint_severe | scripted_baseline_b | 7 | 556780486 | 0.016 | 330.5 | `runs/c773b88b-8b85-4700-8b7a-c4b46d5ab613/trials/9b55df25-0baf-42f4-932e-f112ea3eaf34/video.mp4` | `runs/c773b88b-8b85-4700-8b7a-c4b46d5ab613/trials/9b55df25-0baf-42f4-932e-f112ea3eaf34/trace.jsonl` |
| release_failed | mass_2.0kg | scripted_baseline_b | 0 | 1926800355 | 0.014 | 340.4 | `runs/04d2f5fe-70e2-462e-aac0-4baa96f3db79/trials/99f9a7f6-fe2c-44c7-af6a-54baf49121f3/video.mp4` | `runs/04d2f5fe-70e2-462e-aac0-4baa96f3db79/trials/99f9a7f6-fe2c-44c7-af6a-54baf49121f3/trace.jsonl` |
| release_failed | mass_2.0kg | scripted_baseline_b | 1 | 3300296477 | 0.018 | 338.7 | `runs/04d2f5fe-70e2-462e-aac0-4baa96f3db79/trials/2a2fe751-5a2c-400c-8906-66bc38654e21/video.mp4` | `runs/04d2f5fe-70e2-462e-aac0-4baa96f3db79/trials/2a2fe751-5a2c-400c-8906-66bc38654e21/trace.jsonl` |
| dropped_in_transit | mass_2.0kg | scripted_baseline_b | 2 | 931608108 | 0.189 | 24.1 | `runs/04d2f5fe-70e2-462e-aac0-4baa96f3db79/trials/75a7b0fa-11cc-4676-b993-fd6e4d0ff35b/video.mp4` | `runs/04d2f5fe-70e2-462e-aac0-4baa96f3db79/trials/75a7b0fa-11cc-4676-b993-fd6e4d0ff35b/trace.jsonl` |
| dropped_in_transit | mass_2.0kg | scripted_baseline_b | 3 | 383253587 | 0.266 | 24.1 | `runs/04d2f5fe-70e2-462e-aac0-4baa96f3db79/trials/14f043ab-2ea8-4623-96c1-3c57e2ff9a04/video.mp4` | `runs/04d2f5fe-70e2-462e-aac0-4baa96f3db79/trials/14f043ab-2ea8-4623-96c1-3c57e2ff9a04/trace.jsonl` |
| release_failed | mass_2.0kg | scripted_baseline_b | 4 | 3378088170 | 0.013 | 317.1 | `runs/04d2f5fe-70e2-462e-aac0-4baa96f3db79/trials/85af8203-8629-4af5-8f65-d5940f4a30ba/video.mp4` | `runs/04d2f5fe-70e2-462e-aac0-4baa96f3db79/trials/85af8203-8629-4af5-8f65-d5940f4a30ba/trace.jsonl` |
| dropped_in_transit | mass_2.0kg | scripted_baseline_b | 5 | 1510124407 | 0.143 | 24.1 | `runs/04d2f5fe-70e2-462e-aac0-4baa96f3db79/trials/62f8ffd5-cc92-4949-a8ee-d720df154326/video.mp4` | `runs/04d2f5fe-70e2-462e-aac0-4baa96f3db79/trials/62f8ffd5-cc92-4949-a8ee-d720df154326/trace.jsonl` |
| release_failed | mass_2.0kg | scripted_baseline_b | 6 | 247937657 | 0.012 | 300.9 | `runs/04d2f5fe-70e2-462e-aac0-4baa96f3db79/trials/4e4e4d9b-5591-4c6d-9036-bb8a30627431/video.mp4` | `runs/04d2f5fe-70e2-462e-aac0-4baa96f3db79/trials/4e4e4d9b-5591-4c6d-9036-bb8a30627431/trace.jsonl` |
| placement_outside_target | mass_2.0kg | scripted_baseline_b | 7 | 56613084 | 0.055 | 24.1 | `runs/04d2f5fe-70e2-462e-aac0-4baa96f3db79/trials/32f0debf-e894-4afc-8ac0-9e434a102cf5/video.mp4` | `runs/04d2f5fe-70e2-462e-aac0-4baa96f3db79/trials/32f0debf-e894-4afc-8ac0-9e434a102cf5/trace.jsonl` |
| placement_outside_target | obs_noise_20mm | scripted_baseline_a | 2 | 173069414 | 0.040 | 43.9 | `runs/5b88f507-c85d-4288-abe3-61f81076d10d/trials/5e291f15-c2d3-49f7-91a3-8d55065ab2fb/video.mp4` | `runs/5b88f507-c85d-4288-abe3-61f81076d10d/trials/5e291f15-c2d3-49f7-91a3-8d55065ab2fb/trace.jsonl` |
| placement_outside_target | obs_noise_20mm | scripted_baseline_a | 5 | 102976553 | 0.046 | 41.7 | `runs/5b88f507-c85d-4288-abe3-61f81076d10d/trials/33b55ee5-b245-4fbb-90f2-c7d865a974ed/video.mp4` | `runs/5b88f507-c85d-4288-abe3-61f81076d10d/trials/33b55ee5-b245-4fbb-90f2-c7d865a974ed/trace.jsonl` |
| placement_outside_target | obs_noise_20mm | scripted_baseline_b | 1 | 642476205 | 0.055 | 24.1 | `runs/5b88f507-c85d-4288-abe3-61f81076d10d/trials/cac3a5f0-6628-4e69-a095-6a8911528ed3/video.mp4` | `runs/5b88f507-c85d-4288-abe3-61f81076d10d/trials/cac3a5f0-6628-4e69-a095-6a8911528ed3/trace.jsonl` |
| placement_outside_target | obs_noise_20mm | scripted_baseline_b | 4 | 3959016057 | 0.050 | 23.6 | `runs/5b88f507-c85d-4288-abe3-61f81076d10d/trials/db07b443-2274-4a1a-8e9e-56fb5d5961e1/video.mp4` | `runs/5b88f507-c85d-4288-abe3-61f81076d10d/trials/db07b443-2274-4a1a-8e9e-56fb5d5961e1/trace.jsonl` |
| placement_outside_target | obs_noise_20mm | scripted_baseline_b | 5 | 102976553 | 0.056 | 23.9 | `runs/5b88f507-c85d-4288-abe3-61f81076d10d/trials/bc6ab256-873d-41e8-9f73-d198bf0e28ba/video.mp4` | `runs/5b88f507-c85d-4288-abe3-61f81076d10d/trials/bc6ab256-873d-41e8-9f73-d198bf0e28ba/trace.jsonl` |
| placement_outside_target | target_half_30mm | scripted_baseline_a | 0 | 1678255759 | 0.014 | 40.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/e52cfbe7-bf8a-45c9-8e96-0f0c2efca2e4/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/e52cfbe7-bf8a-45c9-8e96-0f0c2efca2e4/trace.jsonl` |
| placement_outside_target | target_half_30mm | scripted_baseline_a | 1 | 2775143358 | 0.015 | 40.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/02b90d6d-9991-4ebe-8330-debe8ae4ba53/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/02b90d6d-9991-4ebe-8330-debe8ae4ba53/trace.jsonl` |
| placement_outside_target | target_half_30mm | scripted_baseline_a | 2 | 3531623818 | 0.019 | 40.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/bd80ef8f-9d52-479a-a4ef-d4bafae9401e/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/bd80ef8f-9d52-479a-a4ef-d4bafae9401e/trace.jsonl` |
| placement_outside_target | target_half_30mm | scripted_baseline_a | 3 | 1157230675 | 0.017 | 40.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/74b458ea-943a-4282-8475-dc6f44cba4a6/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/74b458ea-943a-4282-8475-dc6f44cba4a6/trace.jsonl` |
| placement_outside_target | target_half_30mm | scripted_baseline_a | 4 | 2900498101 | 0.014 | 40.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/1330143d-f027-488a-b46a-838303dd16ea/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/1330143d-f027-488a-b46a-838303dd16ea/trace.jsonl` |
| placement_outside_target | target_half_30mm | scripted_baseline_a | 5 | 1978606738 | 0.018 | 40.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/792ad3de-0d71-4b61-b916-7635ad78a580/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/792ad3de-0d71-4b61-b916-7635ad78a580/trace.jsonl` |
| placement_outside_target | target_half_30mm | scripted_baseline_a | 6 | 1828216496 | 0.017 | 40.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/bc470600-db9d-4fea-8d6f-6601baf5be2c/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/bc470600-db9d-4fea-8d6f-6601baf5be2c/trace.jsonl` |
| placement_outside_target | target_half_30mm | scripted_baseline_a | 7 | 3592238389 | 0.018 | 41.4 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/14f33431-4192-46d5-8ba5-7793d724dac9/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/14f33431-4192-46d5-8ba5-7793d724dac9/trace.jsonl` |
| placement_outside_target | target_half_30mm | scripted_baseline_b | 0 | 1678255759 | 0.018 | 24.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/65aac22f-a923-4ce0-9e2c-d29cf151a552/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/65aac22f-a923-4ce0-9e2c-d29cf151a552/trace.jsonl` |
| placement_outside_target | target_half_30mm | scripted_baseline_b | 1 | 2775143358 | 0.017 | 24.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/97213653-4eec-4b19-892c-d39931487efc/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/97213653-4eec-4b19-892c-d39931487efc/trace.jsonl` |
| placement_outside_target | target_half_30mm | scripted_baseline_b | 2 | 3531623818 | 0.018 | 24.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/db1d59ca-2aa4-4bd5-9208-959df4a69b49/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/db1d59ca-2aa4-4bd5-9208-959df4a69b49/trace.jsonl` |
| placement_outside_target | target_half_30mm | scripted_baseline_b | 3 | 1157230675 | 0.019 | 24.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/eedfa3e9-695f-4473-b1ed-ffd1297cb580/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/eedfa3e9-695f-4473-b1ed-ffd1297cb580/trace.jsonl` |
| placement_outside_target | target_half_30mm | scripted_baseline_b | 4 | 2900498101 | 0.017 | 24.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/56ae3d2b-1578-4668-b4ea-899d5f2bd731/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/56ae3d2b-1578-4668-b4ea-899d5f2bd731/trace.jsonl` |
| placement_outside_target | target_half_30mm | scripted_baseline_b | 5 | 1978606738 | 0.019 | 24.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/1c900c3e-68d7-4a59-bfa7-9e26ca2cdcb0/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/1c900c3e-68d7-4a59-bfa7-9e26ca2cdcb0/trace.jsonl` |
| placement_outside_target | target_half_30mm | scripted_baseline_b | 6 | 1828216496 | 0.019 | 24.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/dbf4e62e-6527-4448-9b0b-cb79124421be/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/dbf4e62e-6527-4448-9b0b-cb79124421be/trace.jsonl` |
| placement_outside_target | target_half_30mm | scripted_baseline_b | 7 | 3592238389 | 0.019 | 24.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/f2cd9446-0e5b-4471-b548-29270d7303ac/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/f2cd9446-0e5b-4471-b548-29270d7303ac/trace.jsonl` |
| placement_outside_target | target_half_35mm | scripted_baseline_a | 0 | 4002060892 | 0.019 | 40.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/dfc0c473-980b-4180-826c-094962a3fbae/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/dfc0c473-980b-4180-826c-094962a3fbae/trace.jsonl` |
| placement_outside_target | target_half_35mm | scripted_baseline_a | 1 | 2142465603 | 0.019 | 41.4 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/d995d667-d3f8-4197-aeb0-76a8d5cb535d/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/d995d667-d3f8-4197-aeb0-76a8d5cb535d/trace.jsonl` |
| placement_outside_target | target_half_35mm | scripted_baseline_a | 2 | 3175120794 | 0.018 | 40.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/0d49e5ed-9b6a-48ac-a4b1-7606e5503e5c/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/0d49e5ed-9b6a-48ac-a4b1-7606e5503e5c/trace.jsonl` |
| placement_outside_target | target_half_35mm | scripted_baseline_a | 5 | 2746587452 | 0.017 | 40.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/6720e164-c9a6-44ac-b0cd-0ebaf4f2049b/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/6720e164-c9a6-44ac-b0cd-0ebaf4f2049b/trace.jsonl` |
| placement_outside_target | target_half_35mm | scripted_baseline_a | 6 | 3099973674 | 0.019 | 40.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/95a435ae-bf67-46ff-86be-ff6c1ca54229/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/95a435ae-bf67-46ff-86be-ff6c1ca54229/trace.jsonl` |
| placement_outside_target | target_half_35mm | scripted_baseline_a | 7 | 958483315 | 0.017 | 41.5 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/b5044e6e-2c6f-45ce-a474-c41ba8f62f1d/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/b5044e6e-2c6f-45ce-a474-c41ba8f62f1d/trace.jsonl` |
| placement_outside_target | target_half_35mm | scripted_baseline_b | 0 | 4002060892 | 0.020 | 24.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/58e4cf8a-fba9-4590-b588-cd170152e600/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/58e4cf8a-fba9-4590-b588-cd170152e600/trace.jsonl` |
| placement_outside_target | target_half_35mm | scripted_baseline_b | 1 | 2142465603 | 0.016 | 24.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/eb22fc8c-c701-44db-9b05-e1f86b4fe9c2/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/eb22fc8c-c701-44db-9b05-e1f86b4fe9c2/trace.jsonl` |
| placement_outside_target | target_half_35mm | scripted_baseline_b | 2 | 3175120794 | 0.019 | 24.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/4cdf5ef2-7061-423b-bb4b-743ec1bee14f/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/4cdf5ef2-7061-423b-bb4b-743ec1bee14f/trace.jsonl` |
| placement_outside_target | target_half_35mm | scripted_baseline_b | 3 | 2295189173 | 0.019 | 24.1 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/587fe376-d64b-4dd3-8f33-565242841660/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/587fe376-d64b-4dd3-8f33-565242841660/trace.jsonl` |
| placement_outside_target | target_half_35mm | scripted_baseline_b | 4 | 3056692338 | 0.019 | 24.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/a40ebd8a-2819-4635-b34e-f5853c3dcfda/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/a40ebd8a-2819-4635-b34e-f5853c3dcfda/trace.jsonl` |
| placement_outside_target | target_half_35mm | scripted_baseline_b | 5 | 2746587452 | 0.019 | 24.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/ce6d787b-edef-4ed1-a850-c82c5c8c62d2/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/ce6d787b-edef-4ed1-a850-c82c5c8c62d2/trace.jsonl` |
| placement_outside_target | target_half_35mm | scripted_baseline_b | 6 | 3099973674 | 0.017 | 24.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/79e83ab8-2d43-4210-9a90-1a8b6bafb230/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/79e83ab8-2d43-4210-9a90-1a8b6bafb230/trace.jsonl` |
| placement_outside_target | target_half_35mm | scripted_baseline_b | 7 | 958483315 | 0.019 | 24.0 | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/7542c616-cdff-4f3a-8e41-30f358b670d3/video.mp4` | `runs/a2840ca8-4658-478c-9cee-0e511668754f/trials/7542c616-cdff-4f3a-8e41-30f358b670d3/trace.jsonl` |

## Limits

- Panda arm in PyBullet, scripted controllers: no claim about a real robot or any learned policy.
- Eight seeds per cell are a small, bounded start perturbation set; rates carry wide intervals.
- A factor level is a physical stress, not a real-world prior; the envelope is within this simulator.

## Pre-specified hypotheses (frozen before evaluation)

- H1 (descriptive): within each single-factor family, success rate does not increase with severity; the failure envelope is the first level whose success rate is below 100% and the first below 50%.
- H2: the two controllers have different failure envelopes on at least one family (they differ in grip force 20 N vs 12 N, speed, hover height). Direction is NOT predicted.
- H3: failures under tighter targets are placement-offset driven (final block offset from the target centre), not grasp failures. Checked from recorded evidence.
