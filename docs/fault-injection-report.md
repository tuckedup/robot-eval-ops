# Fault-injection report

Generated: 2026-10-13T17:25:02.219823+00:00 (by `robotevalops data faults`; regenerate, do not hand-edit)

Environment: Python 3.11.16 on Windows-10-10.0.26220-SP0; robotevalops 0.1.0, numpy 2.2.6, pandas 3.0.6, pydantic 2.14.1, pybullet 3.2.7, opencv-python-headless 4.12.0.88, boto3 1.43.112, streamlit 1.65.0, lerobot 0.4.4, torch 2.10.0

Fixtures: synthetic (generated frames/states via TrialRecorder, provenance=mock); not robot data.

**Result: 10 of 10 cases executed, 10 passed.** 

A case passes only when the fault was detected, the evidence bytes were preserved, and a misleading success was prevented.

| Case | Executed | Detected codes | Detected | Evidence preserved | Misleading success prevented | Passed |
|---|---|---|---|---|---|---|
| F01_missing_video | yes | missing_video | yes | yes | yes | yes |
| F02_truncated_video | yes | truncated_video | yes | yes | yes | yes |
| F03_nonmonotonic_timestamps | yes | nonmonotonic_timestamps | yes | yes | yes | yes |
| F04_nonfinite_action | yes | nonfinite_value | yes | yes | yes | yes |
| F05_wrong_schema | yes | schema_mismatch | yes | yes | yes | yes |
| F06_missing_model_artifact | yes | missing_model_artifact | yes | yes | yes | yes |
| F07_duplicate_trial_id | yes | duplicate_id | yes | yes | yes | yes |
| F08_hash_mismatch | yes | hash_mismatch | yes | yes | yes | yes |
| F09_transfer_timeout | yes | transfer_timeout | yes | yes | yes | yes |
| F10_interrupted_runner | yes | interrupted_runner | yes | yes | yes | yes |

## Details

### F01_missing_video

- Fault: trial lists video.mp4 but the file is gone
- Expected code: `missing_video`; executed at 2026-10-13T17:25:00.722171Z
- Actionable message produced: video trials/fault_trial/video.mp4 is missing for fault_trial; re-record the trial or locate the file (do not mark the trial successful without video evidence)
- Details: `{"quality": "fail", "accepted": false, "rejection_reasons": ["QA errors present: missing_video"], "quarantined": [], "claimed_outcome": "success", "executed": true}`

### F02_truncated_video

- Fault: H.264 mp4 cut to half its bytes (hash re-recorded)
- Expected code: `truncated_video`; executed at 2026-10-13T17:25:00.821882Z
- Actionable message produced: trials/fault_trial/video.mp4 cannot be opened and has no container index (moov atom): the file looks truncated (interrupted write or partial transfer); re-record or re-download
- Details: `{"quality": "fail", "accepted": false, "rejection_reasons": ["QA errors present: truncated_video"], "quarantined": ["trials/fault_trial/video.mp4"], "claimed_outcome": "success", "original_bytes": 1967, "truncated_bytes": 983, "executed": true}`

### F03_nonmonotonic_timestamps

- Fault: one trace timestamp goes backwards
- Expected code: `nonmonotonic_timestamps`; executed at 2026-10-13T17:25:00.912885Z
- Actionable message produced: trials/fault_trial/trace.jsonl: timestamp goes backwards at row 5 (line 7): t=0.05 after 0.4. The recorder clock or file order is wrong; re-record. Timestamps are never re-sorted or synthesised
- Details: `{"quality": "fail", "accepted": false, "rejection_reasons": ["QA errors present: nonmonotonic_timestamps"], "quarantined": ["trials/fault_trial/trace.jsonl"], "claimed_outcome": "success", "executed": true}`

### F04_nonfinite_action

- Fault: an action value is a literal NaN
- Expected code: `nonfinite_value`; executed at 2026-10-13T17:25:01.097010Z
- Actionable message produced: trials/fault_trial/trace.jsonl: 1 non-finite (NaN/Inf) value(s); first at line 5, row 3 field action[0]. Check the sensor/controller for numerical failure and re-record; do not use this trial for scoring or training
- Details: `{"quality": "fail", "accepted": false, "rejection_reasons": ["QA errors present: nonfinite_value"], "quarantined": ["trials/fault_trial/trace.jsonl"], "claimed_outcome": "success", "executed": true}`

### F05_wrong_schema

- Fault: trace header declares an unsupported schema_version
- Expected code: `schema_mismatch`; executed at 2026-10-13T17:25:01.188347Z
- Actionable message produced: trials/fault_trial/trace.jsonl schema_version '0.0-legacy' != supported '1.0'; migrate or re-record with a matching version
- Details: `{"quality": "fail", "accepted": false, "rejection_reasons": ["QA errors present: schema_mismatch"], "quarantined": ["trials/fault_trial/trace.jsonl"], "claimed_outcome": "success", "executed": true}`

### F06_missing_model_artifact

- Fault: learned-controller trial references models/policy.pt which does not exist
- Expected code: `missing_model_artifact`; executed at 2026-10-13T17:25:01.271295Z
- Actionable message produced: model artifact models/policy.pt referenced by fault_trial does not exist; restore the checkpoint/config or do not claim this controller ran
- Details: `{"quality": "fail", "accepted": false, "rejection_reasons": ["QA errors present: missing_model_artifact"], "quarantined": [], "claimed_outcome": "success", "executed": true}`

### F07_duplicate_trial_id

- Fault: manifest lists the same trial_id twice
- Expected code: `duplicate_id`; executed at 2026-10-13T17:25:01.441879Z
- Actionable message produced: trial_id 'fault_trial' appears 2 times in manifest.json; trial ids must be unique - find the colliding records and re-issue ids (do not delete either record)
- Details: `{"manifest_trials": 2, "claimed_outcome": "success", "executed": true}`

### F08_hash_mismatch

- Fault: one byte of trace.jsonl flipped after its hash was recorded
- Expected code: `hash_mismatch`; executed at 2026-10-13T17:25:01.530393Z
- Actionable message produced: trials/fault_trial/trace.jsonl: recomputed sha256 f84e63fcaffb... != recorded e1668833d345...; the file changed after recording (corruption or tampering). Keep the file as evidence, restore from a verified copy
- Details: `{"quality": "fail", "accepted": false, "rejection_reasons": ["QA errors present: hash_mismatch"], "quarantined": ["trials/fault_trial/trace.jsonl"], "claimed_outcome": "success", "executed": true}`

### F09_transfer_timeout

- Fault: object store times out on every transfer after the first
- Expected code: `transfer_timeout`; executed at 2026-10-13T17:25:01.748175Z
- Actionable message produced: upload runs/fault_session/manifest.json failed after 3 attempt(s): TimeoutError: injected: connection timed out. Check connectivity and credentials, then re-run; completed artifacts are skipped on resume
- Details: `{"max_attempts": 3, "direct_attempts": 3, "bounded_retries": true, "report_ok": false, "state_statuses": {"manifest.json": "uploaded", "trials/fault_trial/trace.jsonl": "failed", "trials/fault_trial/video.mp4": "failed"}, "sleeps": [1.0, 2.0], "checksum_agreement": 0.0, "executed": true}`

### F10_interrupted_runner

- Fault: Runner process dies while a trial is RUNNING; restart must preserve evidence, never report success and require a fresh preflight before any further trial.
- Expected code: `interrupted_runner`; executed at 2026-10-13T17:25:02.218823Z
- Actionable message produced: trial 3ffa145b-ba5d-4803-bcd6-2f1a6022d191 marked aborted/interrupted_runner; session requires a fresh preflight. Runner said: session c15cb80a-526c-4432-a74b-1302265e0ee7 requires a fresh preflight (set after an interruption or halt); run `robotevalops session preflight c15cb80a-526c-4432-a74b-1302265e0ee7` before running trials
- Details: `{"checks": {"interrupted_session_found": true, "one_running_trial_recovered": true, "recovery_idempotent": true, "trial_aborted_interrupted_runner": true, "trial_not_success": true, "partial_file_preserved_unchanged": true, "partial_file_registered_with_hash": true, "pre_crash_evidence_kept": true, "session_requires_fresh_preflight": true, "runner_refused_before_preflight": true, "no_auto_resume": true, "remaining_trial_ran_after_preflight": true}, "session_id": "c15cb80a-526c-4432-a74b-1302265e0ee7", "trial_id": "3ffa145b-ba5d-4803-bcd6-2f1a6022d191", "refusal_message": "session c15cb80a-526c-4432-a74b-1302265e0ee7 requires a fresh preflight (set after an interruption or halt); run `robotevalops session preflight c15cb80a-526c-4432-a74b-1302265e0ee7` before running trials", "evidence": {"interrupted_runner": {"files_on_disk": ["trials/3ffa145b-ba5d-4803-bcd6-2f1a6022d191/trace.jsonl"], "note": "runner died while the trial was RUNNING; partial files preserved, task not judged", "recovered_at": "2026-10-13T17:25:02.020448+00:00"}, "runner": {"note": "pre-crash"}}, "executed": true}`

