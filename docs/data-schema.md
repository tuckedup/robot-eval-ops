# Data schema

Sections: **1. Database and lifecycle (Core)**. Recording/QA/storage sections are owned by Data/storage and
appended by them. On-disk layout: `docs/contracts.md` section 2.

## 1. Database and lifecycle (Core)

`$ROBOTEVALOPS_HOME/robotevalops.db` (SQLite, WAL, `foreign_keys=ON`, `busy_timeout=30000`). Schema version is in
table `schema_version` (current: 1); an unknown newer version raises `SchemaMismatchError`. Keys are UUID4 text.
Timestamps are ISO-8601 UTC text. Every mutation is a `BEGIN IMMEDIATE` transaction.

| Table | Key | Purpose |
|---|---|---|
| `sessions` | `session_id` | one evaluation/collection session; stores `provenance`, `backend`, `device_id`, `calibration_ref`, `requires_fresh_preflight`, `operator_ack_at`, `eval_config_hash` + full `eval_config_json` |
| `trials` | `trial_id` (unique), `UNIQUE(session_id, schedule_position)` | one planned attempt; JSON columns `artifacts_json`, `evidence_json`, `qa_flags_json` |
| `score_edits` | `edit_id` | audit log: editor, mandatory reason, before/after outcome, intervention, source |
| `device_locks` | `device_id` | exclusive lock for a physical device (owner `session_id`) |
| `stop_requests` | `session_id` | persisted software stop request (idempotent) |
| `events` | autoincrement | append-only audit trail (transitions, scoring, hook errors, locks) |

`provenance` (mock / simulation / imported_real_recording / physical_hardware) and `controller_type`
(scripted / learned / teleoperated) are separate columns and are never derived from each other. Every planned trial
stays in `trials` forever; nothing is deleted.

### Trial lifecycle (allowed transitions)

| From | To |
|---|---|
| planned | preflight, aborted |
| preflight | ready, failed, aborted |
| ready | running, preflight (re-check), aborted |
| running | completed, failed, aborted |
| completed / failed / aborted | none (terminal, immutable) |

Terminal state and `termination_reason` must agree (enforced):

| State | Allowed `termination_reason` |
|---|---|
| completed | `success_criterion_met`, `timeout` |
| failed | `preflight_failed`, `infra_failure`, `recording_failure` |
| aborted | `operator_abort`, `software_stop_request`, `safety_stop`, `interrupted_runner`, `not_run` (cancelled before running) |

### Session lifecycle (allowed transitions)

| From | To |
|---|---|
| planned | preflight, aborted |
| preflight | ready, failed, aborted |
| ready | running, preflight, aborted |
| running | completed, failed, aborted, ready (max-trials pause), preflight (crash recovery / halt; always sets `requires_fresh_preflight`) |
| completed / failed / aborted | none |

### Fields that drive metric denominators (contracts section 5)

| Field | Meaning for denominators |
|---|---|
| row exists in `trials` | **planned** |
| `started_at` not null | **attempted/initiated** (reached RUNNING) |
| `state` | completed / failed / aborted counts |
| `task_outcome` + `state` | **unscored** = attempted with `unscored`; success/failure only meaningful for COMPLETED |
| `recording_quality` | `fail` removes a trial from **evaluable** and from autonomous success |
| `intervention` | `assisted` -> intervention rate; anything but `none` is never an autonomous success |
| `termination_reason` | membership in `INFRA_REASONS` -> infra-abort rate |
| `score_source` | `physics_evidence` / `mock_fixture` / `operator_video` / `imported_label`; `none` while unscored |
| `controller_type` | `teleoperated` is never an autonomous success |
| `seed`, `condition_name`, `trial_index` | pairing: same seed per (condition, trial_index) across controllers |

Autonomous success = COMPLETED and `task_outcome=success` and `intervention=none` and not teleoperated and
`recording_quality != fail` (`schemas.is_autonomous_success`).

### Scoring and audit rules

* `record_trial_result` may attach an outcome only to a COMPLETED trial, with a real `score_source`. FAILED/ABORTED
  trials (infra, recording, preflight, interrupted, stop) always stay `unscored`.
* `score_trial` is first-score-only: a second call raises `ScoreProtectionError` (atomic check inside the write
  transaction, so concurrent scorers produce exactly one winner).
* `edit_score` needs an editor and a non-empty reason and writes one `score_edits` row holding the before and after
  values of outcome, intervention and source. Only COMPLETED trials can be scored or edited.

### ScoreSource per provenance (enforced by `score_trial`, `edit_score`, `record_trial_result`)

| Trial provenance | Allowed `score_source` |
|---|---|
| mock | `mock_fixture`, `operator_video` |
| simulation | `physics_evidence`, `operator_video` |
| imported_real_recording | `imported_label`, `operator_video` |
| physical_hardware | `operator_video` only |

Anything else raises `ValueError` and changes nothing (e.g. a mock trial can never carry `physics_evidence`).

### Audit rules for terminal trials

* `register_artifacts`: every change to an existing artifact's sha256/size/status writes an `artifact_changed`
  event with the previous values. On a terminal trial, replacing a recorded sha256 with a different one under a
  good status (present/uploaded/verified) raises `ValueError` unless `actor` and `reason` are passed; recording
  `mismatch`/`failed` (transfer reports) is allowed and audited.
* `set_recording_quality`: the `recording_quality` event stores `previous_quality`, `previous_flags`, `actor`,
  `reason`. Moving a trial away from `fail` requires `actor` and a non-empty `reason`; the first set from
  `unchecked` (Runner QA hook) needs neither.

### Artifacts

`artifacts_json` is a list of `ArtifactRef` (role, POSIX `relpath` relative to `runs/<session_id>/`, `sha256`,
`size_bytes`, `status`). Registration upserts by `relpath`; the Runner records `present` (hash measured from the
file) or `missing` (reported by the adapter but absent). Unsafe paths (`..`, absolute, credential files) are
rejected.

### Session-level flags

* `requires_fresh_preflight`: set by crash recovery and by runner halts; the Runner refuses to run until
  `mark_preflight_passed`.
* `operator_ack_at`: per-session acknowledgement; physical-hardware sessions cannot run without it.
* `eval_config_hash` / `eval_config_json`: the exact template that was planned; the Runner takes controller specs
  from here and verifies each trial's `controller_config_hash` against it.
