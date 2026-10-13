# Demonstration acceptance checklist

Applies to every recorded trial/demonstration before it is used for evaluation scoring or training.
The thresholds below are implemented in `src/robotevalops/qa/trial_qa.py` (`qa_trial`) and must stay in
sync with it. `QAReport.accepted` is true only when **every** item passes; each failed item is listed in
`rejection_reasons`. Acceptance is a data-quality verdict; it says nothing about policy quality.

| # | Criterion | Threshold (code constant) | Rejection reason text starts with |
|---|---|---|---|
| 1 | No QA error flags | 0 flags with severity `error` | `QA errors present:` |
| 2 | Required-metadata completeness | >= 0.98 (`ACCEPT_MIN_COMPLETENESS`) | `required-metadata completeness` |
| 3 | Duration | >= 1.0 s (`ACCEPT_MIN_DURATION_S`); uses `duration_s`, else last-minus-first trace `t` | `duration` |
| 4 | Outcome label present | `task_outcome` is `success` or `failure` (not `unscored`) | `no outcome label` |
| 5 | Operator intervention noted | `intervention` is `none` or `assisted` (not `unknown`) | `operator intervention not noted` |
| 6 | Trial ran to a natural end | `state == completed` | `trial state is` |

Completeness is the filled fraction of the required slots for the trial's provenance
(`REQUIRED_FIELDS_BY_PROVENANCE`, plus `duration_s` once attempted, plus `model_artifact_sha256` and a
`model` artifact for learned controllers). Physical calibration (`calibration_ref`) is required only for
`physical_hardware`; simulation and mock never need it.

## Manual checks the code cannot do (tick before accepting a physical demonstration)

- [ ] The video was watched start to end by the labelling operator; the outcome label matches what happened.
- [ ] Any operator help (hand reset mid-trial, nudge, teleop takeover) is recorded as `assisted`.
- [ ] Camera framing shows the workspace and target region throughout; no lens cover/occlusion unless the condition says so.
- [ ] Calibration file referenced by `calibration_ref` is the one used for this session.
- [ ] No personal data (faces, screens, documents) is visible in the video.

## Notes

- Rejected data is never deleted. `robotevalops data quarantine` copies offending artifacts to
  `runs/<session>/quarantine/<trial_id>/` with an `index.json`; originals stay in place.
- A trial can pass all QA flags and still be rejected (for example unscored): rejection is explicit, not a defect.
- Mock output is never performance evidence; passing this checklist does not change that.
