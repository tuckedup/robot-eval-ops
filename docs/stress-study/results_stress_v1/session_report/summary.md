# RobotEvalOps summary

> SIMULATION — PyBullet Panda arm with rendered simulator frames; not the SO-101 and not hardware

- Sessions: `04d2f5fe-70e2-462e-aac0-4baa96f3db79`, `0e29ff82-9603-4b93-86d0-b7b2215ef302`, `5b88f507-c85d-4288-abe3-61f81076d10d`, `7194b4e9-049a-40fe-8edb-b8ce0069fd7e`, `7600f2fd-c811-4687-83ac-8b73be7e3306`, `961a5ea6-2d80-4605-91f7-b30639a03f25`, `a2840ca8-4658-478c-9cee-0e511668754f`, `c773b88b-8b85-4700-8b7a-c4b46d5ab613`, `e6e9ef01-03a6-4be6-9f06-89531dabf431`
- Provenance: simulation; controller types: scripted
- Generated: 2026-10-14T08:46:56.658141+00:00

## Results (planned / attempted / completed / failed / aborted / unscored)

| scope | planned | attempted | completed | failed | aborted | unscored | evaluable | success/attempted | success/evaluable |
|---|---|---|---|---|---|---|---|---|---|
| ALL | 464 | 464 | 464 | 0 | 0 | 0 | 464 | 0.877 (407/464) [0.844, 0.904] | 0.877 (407/464) [0.844, 0.904] |

## By controller and condition

| controller | type | provenance | condition | planned | attempted | completed | failed | aborted | unscored | evaluable | success/attempted | success/evaluable | intervention rate | infra-abort rate | recording pass rate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scripted_baseline_a | scripted | simulation | delay_1steps | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | delay_2steps | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | delay_4steps | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | delay_8steps | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | friction_0.15 | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 0.875 (7/8) [0.529, 0.978] | 0.875 (7/8) [0.529, 0.978] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | friction_0.25 | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | friction_0.4 | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | friction_0.6 | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | half_size_25mm | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | half_size_30mm | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | half_size_35mm | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 0.875 (7/8) [0.529, 0.978] | 0.875 (7/8) [0.529, 0.978] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | joint_moderate | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 0.875 (7/8) [0.529, 0.978] | 0.875 (7/8) [0.529, 0.978] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | joint_severe | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 0.375 (3/8) [0.137, 0.694] | 0.375 (3/8) [0.137, 0.694] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | mass_0.2kg | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | mass_0.5kg | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | mass_1.0kg | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | mass_2.0kg | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | obs_noise_10mm | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | obs_noise_20mm | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 0.750 (6/8) [0.409, 0.929] | 0.750 (6/8) [0.409, 0.929] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | obs_noise_2mm | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | obs_noise_5mm | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | stress_nominal | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | target_half_30mm | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | target_half_35mm | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 0.250 (2/8) [0.071, 0.591] | 0.250 (2/8) [0.071, 0.591] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | target_half_40mm | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | target_half_50mm | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | yaw_15deg | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | yaw_30deg | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_a | scripted | simulation | yaw_45deg | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | delay_1steps | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | delay_2steps | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | delay_4steps | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | delay_8steps | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | friction_0.15 | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | friction_0.25 | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | friction_0.4 | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | friction_0.6 | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | half_size_25mm | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | half_size_30mm | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | half_size_35mm | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 0.875 (7/8) [0.529, 0.978] | 0.875 (7/8) [0.529, 0.978] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | joint_moderate | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 0.875 (7/8) [0.529, 0.978] | 0.875 (7/8) [0.529, 0.978] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | joint_severe | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 0.500 (4/8) [0.215, 0.785] | 0.500 (4/8) [0.215, 0.785] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | mass_0.2kg | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | mass_0.5kg | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | mass_1.0kg | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | mass_2.0kg | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | obs_noise_10mm | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | obs_noise_20mm | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 0.625 (5/8) [0.306, 0.863] | 0.625 (5/8) [0.306, 0.863] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | obs_noise_2mm | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | obs_noise_5mm | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | stress_nominal | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | target_half_30mm | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | target_half_35mm | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | target_half_40mm | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | target_half_50mm | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | yaw_15deg | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | yaw_30deg | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |
| scripted_baseline_b | scripted | simulation | yaw_45deg | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | 1.000 (8/8) [0.676, 1.000] |

## Durations (recorded values only)

trial duration: n=464 recorded value(s) only; nothing imputed.
reset duration: n=464 recorded value(s) only; nothing imputed.

## Paired comparison

### scripted_baseline_a vs scripted_baseline_b

| condition | pairs | both | A only | B only | neither | A success | B success | exact McNemar p |
|---|---|---|---|---|---|---|---|---|
| ALL | 232 | 194 | 14 | 5 | 19 | 0.897 (208/232) [0.851, 0.929] | 0.858 (199/232) [0.807, 0.897] | 0.0636 |
| delay_1steps | 8 | 8 | 0 | 0 | 0 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | n/a |
| delay_2steps | 8 | 8 | 0 | 0 | 0 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | n/a |
| delay_4steps | 8 | 8 | 0 | 0 | 0 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | n/a |
| delay_8steps | 8 | 8 | 0 | 0 | 0 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | n/a |
| friction_0.15 | 8 | 7 | 0 | 1 | 0 | 0.875 (7/8) [0.529, 0.978] | 1.000 (8/8) [0.676, 1.000] | 1.0000 |
| friction_0.25 | 8 | 8 | 0 | 0 | 0 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | n/a |
| friction_0.4 | 8 | 8 | 0 | 0 | 0 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | n/a |
| friction_0.6 | 8 | 8 | 0 | 0 | 0 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | n/a |
| half_size_25mm | 8 | 8 | 0 | 0 | 0 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | n/a |
| half_size_30mm | 8 | 8 | 0 | 0 | 0 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | n/a |
| half_size_35mm | 8 | 6 | 1 | 1 | 0 | 0.875 (7/8) [0.529, 0.978] | 0.875 (7/8) [0.529, 0.978] | 1.0000 |
| joint_moderate | 8 | 7 | 0 | 0 | 1 | 0.875 (7/8) [0.529, 0.978] | 0.875 (7/8) [0.529, 0.978] | n/a |
| joint_severe | 8 | 2 | 1 | 2 | 3 | 0.375 (3/8) [0.137, 0.694] | 0.500 (4/8) [0.215, 0.785] | 1.0000 |
| mass_0.2kg | 8 | 8 | 0 | 0 | 0 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | n/a |
| mass_0.5kg | 8 | 8 | 0 | 0 | 0 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | n/a |
| mass_1.0kg | 8 | 8 | 0 | 0 | 0 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | n/a |
| mass_2.0kg | 8 | 0 | 8 | 0 | 0 | 1.000 (8/8) [0.676, 1.000] | 0.000 (0/8) [0.000, 0.324] | 0.0078 |
| obs_noise_10mm | 8 | 8 | 0 | 0 | 0 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | n/a |
| obs_noise_20mm | 8 | 4 | 2 | 1 | 1 | 0.750 (6/8) [0.409, 0.929] | 0.625 (5/8) [0.306, 0.863] | 1.0000 |
| obs_noise_2mm | 8 | 8 | 0 | 0 | 0 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | n/a |
| obs_noise_5mm | 8 | 8 | 0 | 0 | 0 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | n/a |
| stress_nominal | 8 | 8 | 0 | 0 | 0 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | n/a |
| target_half_30mm | 8 | 0 | 0 | 0 | 8 | 0.000 (0/8) [0.000, 0.324] | 0.000 (0/8) [0.000, 0.324] | n/a |
| target_half_35mm | 8 | 0 | 2 | 0 | 6 | 0.250 (2/8) [0.071, 0.591] | 0.000 (0/8) [0.000, 0.324] | 0.5000 |
| target_half_40mm | 8 | 8 | 0 | 0 | 0 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | n/a |
| target_half_50mm | 8 | 8 | 0 | 0 | 0 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | n/a |
| yaw_15deg | 8 | 8 | 0 | 0 | 0 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | n/a |
| yaw_30deg | 8 | 8 | 0 | 0 | 0 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | n/a |
| yaw_45deg | 8 | 8 | 0 | 0 | 0 | 1.000 (8/8) [0.676, 1.000] | 1.000 (8/8) [0.676, 1.000] | n/a |

The exact McNemar p-value uses only discordant pairs. With the small n typical here it does not support significance claims: it assumes independent pairs, a fixed paired design, and a pre-specified test, and ignores multiple comparisons across conditions. Treat differences as descriptive.

## Failure categories

| class | trials |
|---|---|
| autonomous_success | 407 |
| task_failure | 57 |

Every trial appears in exactly one row. infra/abort trials stay unscored and are never counted as task failures; task failures are completed trials scored failure.

## QA and artifact completeness

- artifact completeness: 1.000 (1392/1392) [0.997, 1.000] (expected 1392, missing 0)
- checksums: verified 0, mismatch 0, unverified 1392; agreement n/a (n=0)
- recording quality pass rate: 1.000 (464/464) [0.992, 1.000]

## Warnings

- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=delay_1steps] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=delay_2steps] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=delay_4steps] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=delay_8steps] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=friction_0.15] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=friction_0.25] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=friction_0.4] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=friction_0.6] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=half_size_25mm] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=half_size_30mm] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=half_size_35mm] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=joint_moderate] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=joint_severe] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=mass_0.2kg] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=mass_0.5kg] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=mass_1.0kg] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=mass_2.0kg] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=obs_noise_10mm] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=obs_noise_20mm] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=obs_noise_2mm] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=obs_noise_5mm] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=stress_nominal] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=target_half_30mm] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=target_half_35mm] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=target_half_40mm] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=target_half_50mm] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=yaw_15deg] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=yaw_30deg] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_a, controller_version=1, controller_config_hash=a1aa4189cacdb2927bc3262fd03343339e21447d388f027152b12a844d8519f7, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=yaw_45deg] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=delay_1steps] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=delay_2steps] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=delay_4steps] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=delay_8steps] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=friction_0.15] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=friction_0.25] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=friction_0.4] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=friction_0.6] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=half_size_25mm] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=half_size_30mm] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=half_size_35mm] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=joint_moderate] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=joint_severe] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=mass_0.2kg] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=mass_0.5kg] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=mass_1.0kg] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=mass_2.0kg] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=obs_noise_10mm] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=obs_noise_20mm] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=obs_noise_2mm] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=obs_noise_5mm] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=stress_nominal] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=target_half_30mm] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=target_half_35mm] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=target_half_40mm] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=target_half_50mm] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=yaw_15deg] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=yaw_30deg] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.
- [controller_id=scripted_baseline_b, controller_version=1, controller_config_hash=2d94da7084af9d1d11e544fbf5994e31be849783dc3c18c8f73e344fa2c2bad6, controller_type=scripted, provenance=simulation, rubric_version=rubric-v1, condition=yaw_45deg] small n: 8 evaluable trial(s) (< 20); intervals are wide and differences are not reliable.

## Limitations

- The controllers evaluated by this repository are scripted, state-based programs reading simulator state; they are not learned policies and not trained checkpoints.
- Simulation results use a PyBullet Panda arm with rendered simulator frames. This is not the SO-101 arm and not physical hardware; no conclusion about real-robot performance follows.
- Mock-provenance results are seeded fixtures and are never evidence of robotics performance.
- Visual-only conditions (lighting, background, occlusion) do not change what a state-based controller reads; they say nothing about the visual robustness of a learned policy.
- Small sample sizes: Wilson intervals are wide and any difference between controllers is descriptive. p-values from so few discordant pairs do not support significance claims.
- Scoring agreement between independent human scorers and reset-time improvements are not measured by this report; they need independent human measurement (see docs/evaluation-protocol.md).

## Data sources

- session `7600f2fd-c811-4687-83ac-8b73be7e3306` (stress_v1-evaluation-reference): run dir `runs/7600f2fd-c811-4687-83ac-8b73be7e3306`, manifest `runs/7600f2fd-c811-4687-83ac-8b73be7e3306/manifest.json` (not found), eval_config_hash `6411eb9a8befc7801ee44ecbd48398ae3606b20c586fe26449b1f8d4a73ef9df`
- session `04d2f5fe-70e2-462e-aac0-4baa96f3db79` (stress_v1-evaluation-mass): run dir `runs/04d2f5fe-70e2-462e-aac0-4baa96f3db79`, manifest `runs/04d2f5fe-70e2-462e-aac0-4baa96f3db79/manifest.json` (not found), eval_config_hash `15ac33d647d889f3af21689a9a2079d489f405d56cf614ce8a9e8855ac7a4036`
- session `961a5ea6-2d80-4605-91f7-b30639a03f25` (stress_v1-evaluation-friction): run dir `runs/961a5ea6-2d80-4605-91f7-b30639a03f25`, manifest `runs/961a5ea6-2d80-4605-91f7-b30639a03f25/manifest.json` (not found), eval_config_hash `f3b8588847fc02beb703445823a592a644c415bbd9c9bba72708a812e92dc079`
- session `7194b4e9-049a-40fe-8edb-b8ce0069fd7e` (stress_v1-evaluation-size): run dir `runs/7194b4e9-049a-40fe-8edb-b8ce0069fd7e`, manifest `runs/7194b4e9-049a-40fe-8edb-b8ce0069fd7e/manifest.json` (not found), eval_config_hash `bad5c5d239b72d087a1437d985e57089602e46612c478bf142cb20845ed69c3f`
- session `e6e9ef01-03a6-4be6-9f06-89531dabf431` (stress_v1-evaluation-yaw): run dir `runs/e6e9ef01-03a6-4be6-9f06-89531dabf431`, manifest `runs/e6e9ef01-03a6-4be6-9f06-89531dabf431/manifest.json` (not found), eval_config_hash `8b12254832929e50b129c0c41fdc7ff8024ebcf72cd5ea557ed5b620946ae2c9`
- session `a2840ca8-4658-478c-9cee-0e511668754f` (stress_v1-evaluation-target): run dir `runs/a2840ca8-4658-478c-9cee-0e511668754f`, manifest `runs/a2840ca8-4658-478c-9cee-0e511668754f/manifest.json` (not found), eval_config_hash `90e715be13679f6b6558283c5036baadcc47a140a74afc263cf25ed8b730d7e1`
- session `0e29ff82-9603-4b93-86d0-b7b2215ef302` (stress_v1-evaluation-delay): run dir `runs/0e29ff82-9603-4b93-86d0-b7b2215ef302`, manifest `runs/0e29ff82-9603-4b93-86d0-b7b2215ef302/manifest.json` (not found), eval_config_hash `10564e250215499b29f73a22c7f687e06feb7f2dd9364b5959862c377f67d5ae`
- session `5b88f507-c85d-4288-abe3-61f81076d10d` (stress_v1-evaluation-noise): run dir `runs/5b88f507-c85d-4288-abe3-61f81076d10d`, manifest `runs/5b88f507-c85d-4288-abe3-61f81076d10d/manifest.json` (not found), eval_config_hash `1473057f4887a30c953456c71077565f40748365541b48323dd3d47558b26a15`
- session `c773b88b-8b85-4700-8b7a-c4b46d5ab613` (stress_v1-evaluation-joint): run dir `runs/c773b88b-8b85-4700-8b7a-c4b46d5ab613`, manifest `runs/c773b88b-8b85-4700-8b7a-c4b46d5ab613/manifest.json` (not found), eval_config_hash `be5e7258ca89fb2daf37e5481980572f4c86b8e59f50c14b11aca71a000b6dbd`
