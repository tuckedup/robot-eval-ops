# Scoring rubric `rubric-v1`

Version: rubric-v1 (pick_place_block_v1). Any change to these rules needs a new version; never edit a published
version in place. Record the rubric version with every score.

## Inputs

- The trial video (`trials/<trial_id>/video.mp4`) and, if needed, the trace.
- Attempt timeout: 30 s. Dwell requirement: 2 s.

## Outcome

Mark **success** only if ALL are true within the attempt:

1. The block is entirely inside the target region (no part touches or crosses the boundary).
2. The block is released (the gripper has let go).
3. Conditions 1 and 2 hold continuously for 2 s.

Otherwise mark **failure** (examples: timeout, dropped, outside the region, still held, moved out during dwell).

If the video is unusable (missing, cut, cannot judge), do not guess: leave the trial unscored and report it with the
bug template.

## Intervention

- `none`: nobody touched the robot, block or scene during the attempt.
- `assisted`: any operator help (touching or moving the block, guiding the arm, restarting, nudging). An assisted
  success is never counted as autonomous.
- If you cannot tell, ask the operator. Do not choose `none` to be safe.

## Procedure

1. Score without looking at other scorers' answers.
2. Enter your name; the first score uses `report score`, changes use `report edit-score` with a reason.
3. For agreement checks, two scorers fill `scoring-agreement.csv` independently.

## Not a rubric item

Speed, smoothness and appearance do not change the outcome. Infrastructure/recording failures and aborts are not
scored.
