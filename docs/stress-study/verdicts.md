# Verdicts on the frozen hypotheses (stress_v1)

Computed from `results_stress_v1/results.json` (464 attempted trials, 8 seeds per cell). Descriptive, simulation only.

* **H1 (success does not increase with severity within a single-factor family): held in all 14 controller x family
  series.** Success is non-increasing with severity everywhere (for example A noise 8/8, 8/8, 8/8, 8/8, 6/8; B mass
  8/8 up to 1 kg then 0/8 at 2 kg; A target 8/8, 8/8, 8/8, 2/8, 0/8). Eight seeds per cell cannot resolve small
  effects: A's single failures at friction 0.15 and half-size 35 mm (1/8 each) are not evidence of a threshold.
* **H2 (the controllers have different failure envelopes on at least one family): supported.** Mass: A 8/8 at 2 kg,
  B 0/8. Friction: A 7/8 at 0.15, B 8/8. Target: A 2/8 at 35 mm, B 0/8 (both 0/8 at 30 mm). Direction was not
  predicted. The 2 kg failures of B are a mix (4 release_failed, 3 dropped_in_transit, 1 placement_outside_target);
  attributing them to B's lower grip force (12 N vs 20 N) is a plausible reading that was **not** tested by ablation.
* **H3 (tight-target failures are placement-offset driven, not grasp failures): supported.** All 30 failures in the
  target family are `placement_outside_target`, grasp and lift had succeeded, and the block ended 1.4-2.0 cm from the
  target centre, the same offset both controllers show at nominal (A 1.6 cm, B 1.8 cm). The simulator's tolerance
  (block corners strictly inside the square) therefore fails once the half-width approaches that fixed bias plus the
  block half-size (0.02 m).

Also visible: the combined `joint_severe` condition fails 5/8 (A) and 4/8 (B), all placement outside the target.
Peak contact force in the evidence reaches 260-320 N in some size/joint-severe trials; these are recorded values from
the simulator's contact solver and were not investigated further.
