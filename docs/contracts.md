# Shared contracts (lead-owned)

Authoritative for all workers. Code contracts: `schemas.py`, `lifecycle_rules.py`, `errors.py`, `util.py`,
`adapters/base.py`, `storage/base.py`. To change any of them, send the lead a request with the reason.

## 1. File ownership (no two workers edit the same file)

| Owner | Source subtree | Test subtree |
|---|---|---|
| Lead | `pyproject.toml`, `uv.lock`, `schemas.py`, `lifecycle_rules.py`, `errors.py`, `util.py`, `adapters/base.py`, `storage/base.py`, `cli/main.py`, `cli/demo_cmds.py`, `scripts/`, `.github/`, `Dockerfile`, `README.md`, `CLAUDE.md`, `.claude/`, `docs/implementation-status.md`, `docs/verification.md`, `docs/resume-evidence.md`, `src/robotevalops/configs/targets.yaml`, `tests/integration/` | `tests/integration/` |
| Core | `core/**`, `cli/session_cmds.py`, `config.py` (eval-config YAML loading + `src/robotevalops/configs/*.yaml` eval templates), `docs/architecture.md`, `docs/data-schema.md` (DB + lifecycle parts) | `tests/core/**` |
| Robotics | `adapters/mock.py`, `adapters/sim_*.py`, `adapters/hardware_*.py`, `adapters/lerobot_*.py`, `adapters/registry.py`, `controllers/**`, `cli/robot_cmds.py`, `src/robotevalops/configs/hardware/**`, `src/robotevalops/configs/controllers/**`, `docs/hardware-setup.md` | `tests/robotics/**` |
| Data/storage | `recording/**`, `qa/**`, `storage/{local,s3,package,retry}.py`, `faults/**`, `cli/data_cmds.py`, `docs/troubleshooting.md` (storage/QA parts), `docs/templates/**` (acceptance checklist) | `tests/data/**` |
| Eval/reporting | `metrics/**`, `reporting/**`, `dashboard/**`, `scoring.py`, `cli/report_cmds.py`, `docs/evaluation-protocol.md`, `docs/operating-procedure.md`, rubric/reset-checklist/bug template under `docs/templates/` | `tests/eval/**` |
| Verifier | READ-ONLY on `src/`; writes only `tests/verification/**`, `docs/verification-findings.md` | `tests/verification/**` |

Controllers package: `src/robotevalops/controllers/` (scripted controllers; Robotics owns it).

## 2. On-disk layout

```
$ROBOTEVALOPS_HOME/            (default ./data, gitignored)
  robotevalops.db              SQLite (core)
  runs/<session_id>/
    manifest.json              RunManifest (data/storage writes; covers every planned trial)
    session.log.jsonl          structured logs
    trials/<trial_id>/{video.mp4, trace.jsonl, trial.log.jsonl, controller.json}
    qa/<trial_id>.qa.json      QAReport
    quarantine/<trial_id>/...  COPIES of bad artifacts (sources are never deleted)
  store/                       LocalArtifactStore root; keys "runs/<session_id>/..." (identical to S3 keys)
  reports/<session_id>/...     report.html, summary.{md,csv,json}, plots/
```
Artifact `relpath` values are POSIX, relative to `runs/<session_id>/`. Store key =
`runs/<session_id>/<relpath>`.

`trace.jsonl`: line 1 is a `TraceHeader` JSON object; each following line a `TraceRow`. Python's `json` may
emit `NaN`/`Infinity`; QA must parse with `parse_constant` capture and flag them as `nonfinite_value`.
`trace` timestamps are measured by the recorder; never synthesise missing ones.

## 3. Core public API: `robotevalops.core.service.EvalService(home)` (dashboard/report/CLI use ONLY this)

```
create_session(name, provenance, backend, *, task=None, purpose="evaluation", operator="", device_id=None,
               calibration_ref=None, eval_config: EvalConfig|None=None, notes="") -> SessionRecord
plan_trials(session_id, eval_config) -> list[TrialRecord]     # deterministic schedule, paired across controllers
get_session(id) / list_sessions() / get_trial(id) / list_trials(session_id, state=None, ...)
transition_session(id, new_state, *, note="") / transition_trial(id, new_state, **fields)  # validates rules
mark_preflight_passed(session_id)                  # clears requires_fresh_preflight
acknowledge_operator(session_id, operator)         # hardware per-session ack (stored)
record_trial_result(trial_id, *, termination_reason, duration_s, task_outcome=None, score_source=None,
                    intervention=None, evidence=None, artifacts=None, recording_quality=None, reset_duration_s=None)
register_artifacts(trial_id, list[ArtifactRef]) / set_recording_quality(trial_id, quality, qa_flags)
score_trial(trial_id, outcome, *, source, scorer, intervention=None)   # first score only; raises ScoreProtectionError
                                                                       # if already scored
edit_score(trial_id, outcome, *, intervention=None, source, editor, reason) -> ScoreEdit  # audited
list_score_edits(trial_id)
request_stop(session_id)                           # idempotent; persisted flag the Runner polls
find_interrupted() / recover_interrupted(session_id) -> list[TrialRecord]
acquire_device(device_id, session_id) / release_device(...)    # raises DeviceBusyError
export_manifest(session_id) -> RunManifest
```
`Runner` (`core/runner.py`) is the only component that calls adapters. Signature:
`Runner(service, adapter_factory: Callable[[SessionRecord], RobotAdapter], controller_factory: Callable[[ControllerSpec], Controller], condition_lookup, logger=None)`; `.run_session(session_id, *, max_trials=None)`.

Behavioural rules the Core must implement and test: every planned trial stays in the DB forever; a failed
infra/recording run is `FAILED` with `task_outcome=UNSCORED` (never success); `intervention != NONE` can never
produce an autonomous success; on restart every `RUNNING` trial becomes `ABORTED/interrupted_runner`, the session
goes to `PREFLIGHT` with `requires_fresh_preflight=True`, and the Runner refuses to run any trial for a session
with that flag set until `mark_preflight_passed`; physical sessions additionally require `operator_ack_at`.

## 4. CLI surface (Typer)

`robotevalops session {create,plan,list,show,preflight,ack,run,recover,stop,export-manifest}` (core),
`robotevalops robot {adapters,sim-smoke,hardware-check,lerobot-info,teleop,record,rollout,import-dataset}` (robotics),
`robotevalops data {validate,quarantine,package,upload,download,verify,faults}` (data/storage),
`robotevalops report {score,edit-score,metrics,compare,export,html,dashboard}` (eval),
`robotevalops demo {run}` (lead; chains the above).
All commands print machine-readable JSON with `--json` and use non-zero exit codes on failures.

## 5. Metric denominators (single definition; eval engineer implements exactly this)

- **planned** = all trials in the session(s). **attempted/initiated** = `started_at` set (reached RUNNING).
- **completed / failed / aborted** = lifecycle state counts. **unscored** = attempted with `task_outcome=unscored`.
- **evaluable** = `COMPLETED` ∧ scored (success|failure) ∧ `recording_quality != fail`.
- **Autonomous success rate (per initiated attempt)** = autonomous successes / attempted. **(per evaluable)** =
  autonomous successes / evaluable. Both reported; Wilson 95% interval for both.
- **Intervention rate** = `intervention == assisted` / attempted. **Infra-abort rate** = termination in
  `INFRA_REASONS` / attempted. **Recording-quality pass rate** = `pass` / attempted. **Artifact completeness** =
  present+hash-recorded artifacts / expected artifacts. **Checksum agreement** = verified / transferred.
- Planned-but-never-attempted trials appear in the planned row and never vanish. Quality exclusions are shown,
  not hidden. Pairing: same seed per (condition, trial_index) across controllers; paired comparison reports
  discordant counts only and states that n is too small for significance claims unless an exact test is run.

## 6. The ten fault cases (ids fixed)

`F01_missing_video`, `F02_truncated_video`, `F03_nonmonotonic_timestamps`, `F04_nonfinite_action`,
`F05_wrong_schema`, `F06_missing_model_artifact`, `F07_duplicate_trial_id`, `F08_hash_mismatch`,
`F09_transfer_timeout`, `F10_interrupted_runner`. F01–F09 live in `faults/` (data/storage); F10's scenario function
`core/fault_interrupted.py::run_interrupted_runner_case(workdir) -> FaultResult` is Core's. Each result must show
detection, evidence preserved, and misleading success prevented.

## 7. Provenance and wording rules

Mock output is labelled `mock` everywhere (file names, reports, dashboard) and is never performance evidence.
Sim frames are "rendered simulator frames". Panda is Panda, never SO-101. Do not write "verified" about anything
not actually executed in this repository's environment.
