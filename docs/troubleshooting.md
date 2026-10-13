# Troubleshooting

This file holds the storage / QA sections (Data/storage owner). Other sections may be added by other owners.

## QA codes and remediation

`robotevalops data validate <run_dir>` runs QA per trial and writes `qa/<trial_id>.qa.json`. Any `error`
flag makes the trial's `recording_quality` = `fail`; warnings give `flagged`. Checks only observe: they never
repair, re-sort, interpolate or invent timestamps/states. Originals are never moved or deleted.

| Code | Severity | Meaning | What to do |
|---|---|---|---|
| `missing_video` | error | Video file absent (or not listed when required) | Re-record, or restore the file from the store (`data download`); do not label the trial a success without video evidence. Use `--no-require-video` only for state-only backends. |
| `truncated_video` | error | Zero-byte, no container index (moov atom), header frame count > decoded frames, or fewer decoded frames than trace rows | Re-record or re-download. If frames are intentionally sparser than trace rows, pass `expected_frames` to `qa_trial`. |
| `undecodable_frames` | error | File has an index but OpenCV cannot open/decode frames | Re-encode (H.264 mp4) or re-record. |
| `nonmonotonic_timestamps` | error | `t` decreases (equal values are allowed); message names the first row index and file line | Fix the recorder clock; re-record. |
| `nonfinite_value` | error | NaN/Infinity in `t`/`state`/`action` (including bare `NaN` literals) | Find the numerical failure in the sensor/controller; re-record. |
| `missing_field` | error/warning | Header/row field missing, vector length differs from header names, required manifest field absent; warning when an artifact has no recorded sha256 | Fix the recorder or complete the manifest; values are never guessed. |
| `schema_mismatch` | error | Header `kind`/`schema_version` wrong, corrupt JSON line, manifest version mismatch | Migrate or re-record with a matching version. |
| `missing_artifact` | error | A listed artifact is not on disk | Restore from the store or re-record. |
| `missing_model_artifact` | error | Learned controller lists no MODEL artifact, or the file is absent | Restore the checkpoint (with sha256) or relabel the controller; a scripted config is not a learned checkpoint. |
| `duplicate_id` | error | Same `trial_id` (or episode index) more than once | Re-issue ids; never merge or delete either record. |
| `missing_outcome` | warning | Completed trial is `unscored` | Score from physics evidence or operator video review. |
| `hash_mismatch` | error | Recomputed SHA-256 differs from the recorded one | Treat as corruption/tampering: keep the file as evidence, restore from a verified copy. |
| `low_completeness` | warning | Required-metadata completeness < 0.98 | See the accompanying `missing_field` flags. |
| `transfer_timeout` | error | Upload/download exhausted bounded retries | Check network/credentials and re-run; completed artifacts are skipped (resume state in `<run_dir>/.transfer/`). |
| `interrupted_runner` | error | Runner crashed mid-trial (Core) | Run session recovery, then a fresh preflight. |

Acceptance rubric: see `docs/templates/demonstration-acceptance-checklist.md`.

## Quarantine

`robotevalops data quarantine <run_dir> [--trial ID]` copies offending artifacts of failed trials into
`runs/<session>/quarantine/<trial_id>/<relpath>` and writes `index.json` (hashes, codes, flags). Status
`quarantined` appears in the QA report only; the original files remain where they were.

## Storage

- Local store default: `$ROBOTEVALOPS_HOME/store` (keys `runs/<session_id>/<relpath>`, same as S3).
  Hashes live in `.meta/<key>.sha256` sidecars; `verify` re-reads the bytes and recomputes SHA-256.
- `ArtifactOverwriteError`: the key already holds different bytes. Artifacts are immutable; use a new key.
- Upload interrupted: re-run the same `data upload`; `.transfer/upload_state.json` skips finished artifacts.
  `data verify` then re-downloads and recomputes every hash. Checksum agreement = verified / transferred.
- Files blocked from packaging (see `data package`): `.env`, `credentials`, `id_rsa`, `*.pem`, `*.key`,
  `.aws/`, `.ssh/`, `.git/`, symlinks, `*.tmp`. They are listed, never uploaded.
- Fault suite: `robotevalops data faults` re-executes F01-F10 and rewrites `docs/fault-injection-report.md`.
- OpenCV may print `moov atom not found` to stderr when probing a truncated video; that is expected.

S3: see `docs/storage-aws.md`.
