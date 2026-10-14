# Independent verification findings (V1)

Verifier: independent of the implementation. Scope: read-only on `src/`, `src/robotevalops/configs/`, other docs and other workers'
tests; added tests only under `tests/verification/`. Date of runs: 2026-10-13, Windows 11, Python 3.11 (`.venv`).
Everything below was run in this environment unless stated; nothing was run against real hardware or real AWS.

Every defect that is reproducible as a test is committed as `xfail(strict=True, reason="VF-nn ...")` in
`tests/verification/`: the test goes red (XPASS strict) the moment the defect is fixed, which is the signal to remove
the marker. Tests that pass document attacks that failed to break the system.

## 1. Summary

| Severity | Count | IDs |
|---|---|---|
| blocker | 1 | VF-13b |
| major | 5 | VF-01, VF-02, VF-12, VF-13, VF-18 |
| minor | 13 | VF-03, VF-04, VF-05, VF-06, VF-07, VF-08, VF-09, VF-10, VF-11, VF-14, VF-15, VF-16, VF-17 |

Total 19 findings. Severity meaning: blocker = a headline claim/invariant is false on the documented path; major =
a success/QA verdict can be wrong, or the acceptance gate is red; minor = hardening, audit, wording.

## 2. Findings

| ID | Sev | Area | Evidence | Repro | Suggested owner |
|---|---|---|---|---|---|
| VF-13b | **blocker** | QA wiring / metrics | The documented flow (`session run`, then `data validate`, `report metrics`) never feeds QA into the database. `session run` installs no `qa_hook` (only `demo run` does, `cli/demo_cmds.py::_make_runner`), `data validate` never touches the DB. Measured: 12 mock trials run through the CLI, every `video.mp4` truncated to 50 bytes, manifest exported, `data validate` reports `error_count 24`, yet `report metrics` still shows `evaluable 12`, `autonomous_successes 9`, `recording_pass_rate k=0`, and every trial is `recording_quality=unchecked`. `docs/troubleshooting.md` says any QA error makes `recording_quality = fail`; `docs/walkthrough-90s.md` says no fault can end as a success. That is only true inside `demo run`. | `pytest tests/verification/test_storage_qa.py -k corrupt_recording_is_not_counted` (xfail strict); manual script printed `validate: 1 24` then `{'evaluable': 12, 'autonomous_successes': 9}` | Core (`session_cmds.run`: wire qa_hook + manifest_hook), Data (`data validate` should persist via `EvalService.set_recording_quality`), Eval (warn when quality is `unchecked` in metrics) |
| VF-13 | major | CLI / docs | `docs/operating-procedure.md` section 5 step `data validate runs/<id>` crashes after `session run`: no `manifest.json` exists (only the demo writes it), and `read_manifest` raises an unhandled `FileNotFoundError` traceback (exit 1) instead of the documented exit 2 "expected error". | `pytest tests/verification/test_storage_qa.py -k data_validate_after_session_run` (xfail strict) | Data (`_guard` should catch `OSError`), Core (write manifest after run) |
| VF-01 | major | Sim success evidence | A controller that never closes the gripper and only pushes the block into the region (lift 7.6e-5 m, `both_finger_contact_steps` 0) is scored SUCCESS by `physics_evidence`, dwell 2.000 s, quality pass. Success never requires a grasp/lift although the task is "pick the block" and the rubric says the block must be "released" (`adapters/sim_pybullet.py::_update_task`: `inside and released`). `lift_m` and `both_finger_contact_steps` are recorded as evidence but not gated. Scripted demo trials are unaffected (lift 0.20 and 0.26 m). | `pytest tests/verification/test_sim_success_audit.py -k pushing_block` (xfail strict). Measured in a throwaway run: push offsets -0.10/-0.07 give `success_criterion_met True`, block at y=0.18/0.21 | Robotics (decide: require lift >= x and finger contact, or document that push-placement counts; update rubric either way) |
| VF-02 | major | Sim success evidence / config validation | `dwell_required_s <= 0` is accepted by `TaskSpec` (no validator) and by the adapter, and `self._dwell + 1e-9 >= self._dwell_required` is true on step 1. A no-op controller then SUCCEEDS at t=0.05 s with the block 35 cm from the region (`all_corners_inside False`). Same for `-1`. `attempt_timeout_s: 0` is also accepted. | `pytest tests/verification/test_sim_success_audit.py -k zero_dwell` (xfail strict). Direct: `dwell0 success_criterion_met True 0.05 False [0.4999, -0.1499, 0.0199]` | Lead (`schemas.TaskSpec`: `gt=0`, and rubric-v1 pins 2.0/30), Robotics (adapter should refuse) |
| VF-12 | major | QA acceptance | A trace with a valid header and ZERO rows plus a decodable video gets `quality=pass`, no flags, `accepted=True` from `qa_trial` (expected frames is taken from the row count, so 0 rows expect 0 frames; `duration_s` comes from the manifest). An empty demonstration is accepted. | `pytest tests/verification/test_storage_qa.py -k header_only` (xfail strict) | Data (`qa/trial_qa.py`/`checks.py`: zero rows is an ERROR) |
| VF-18 | major (gate) | Lint gate | `ruff check .` reports 8 errors (7 x E501 and one I001 import order in `cli/demo_cmds.py`, one E501 in `integration.py`); `ruff format --check .` wants to reformat `cli/demo_cmds.py`. Both are lead-owned files. `mypy src` is clean. | `.venv/Scripts/python.exe -m ruff check .` | Lead |
| VF-03 | minor | Storage | `LocalArtifactStore.put_file` decides "identical bytes already stored" from the sidecar hash, not the stored bytes. After the stored object is corrupted, re-uploading the original returns `UPLOADED, skipped_identical=True` and neither repairs nor flags it (`verify` does catch it: the sidecar is not trusted there). S3 `put_file` has the same shape (trusts object metadata `sha256`). | `pytest tests/verification/test_storage_qa.py -k reupload_does_not_trust_sidecar` (xfail strict) | Data |
| VF-11 | minor | Storage | Upload resume state `.transfer/upload_state.json` is trusted without asking the store. After deleting `store/runs`, `upload_run` again returns `ok=True`, artifact `uploaded` with detail "skipped: already uploaded ... (resume state)" while `store.exists(...)` is False. Documented flow requires `verify` after upload, which would show FAILED. | `pytest tests/verification/test_storage_qa.py -k resume_state_does_not_hide` (xfail strict). Direct: `after loss: True [('uploaded','skipped: ...')] False` | Data |
| VF-10 | minor | Storage / credentials | Credential screening is a short deny-list. Blocked (verified): `.env`, `credentials`, `id_rsa`, `*.pem`, `*.key`, `.p12`, `.netrc`, `.aws/`, `.ssh/`, `.git/`, `config.json`. COLLECTED for upload (verified): `credentials.json`, `.env.local`, `prod.env`, `.git-credentials`, `id_ecdsa`, `secrets.yaml`, `.npmrc`, `service-account.json`, `token.txt`. Run dirs are tool-generated so exposure needs a stray file, hence minor. Side effect: `config.json` (a normal policy checkpoint file) is blocked. | `pytest tests/verification/test_storage_qa.py -k common_secret_file_names` (xfail strict) | Data / Lead (`util.FORBIDDEN_*`) |
| VF-04 | minor | Accounting | `EvalService.score_trial/edit_score` accept any `ScoreSource` for any provenance (a mock trial can be hand-labelled `physics_evidence`). Only `scoring.py` restricts to human sources. | `pytest tests/verification/test_lifecycle_accounting.py -k score_source_must_match` (xfail strict) | Core |
| VF-05 | minor | Accounting / audit | `register_artifacts` on a COMPLETED trial silently replaces `sha256/size/status` of an existing artifact; no audit event stores the previous hash. | `pytest ... -k terminal_trial_artifact_hash` (xfail strict) | Core |
| VF-06 | minor | Accounting / audit | `set_recording_quality` can flip a terminal trial `fail -> pass` with no actor/reason; the `recording_quality` event records only the new value. | `pytest ... -k quality_fail_cannot_be_flipped` (xfail strict) | Core |
| VF-07 | minor | Hardware gate | `HardwareGate.refusal` skips the "ack belongs to a different session" check when `session_id` is empty (the default of `SO101HardwareAdapter`), so another session's acknowledgement passes. Not reachable via CLI or registry (both pass a session id). | `pytest tests/verification/test_hardware_safety.py -k ack_for_other_session` (xfail strict) | Robotics |
| VF-08 | minor | Accounting (documented) | On a physical session with `ROBOTEVALOPS_HARDWARE_MODE` unset, `session run` reaches `adapter.reset`, gets `HardwareRefusedError`, and records the trial as RUNNING then FAILED/`infra_failure` (started_at set, session needs fresh preflight). A refusal is counted as an attempted infra failure and raises the infra-abort rate. `docs/architecture.md` states this is intended for reset failures, but a gate refusal is a different thing. No lerobot process was launched (recorder-checked). | `pytest tests/verification/test_hardware_safety.py -k session_run_physical_cli_gates` (passes; asserts the behaviour) | Core / Robotics |
| VF-09 | minor | Input validation | `ID_RE`, `PORT_RE`, `REPO_RE` use `re.match` with `$`, which accepts a trailing newline: `follower_id='fol\n'`, `follower_port='COM3\n'`, `dataset_repo_id='a/b\n'` validate and land in argv elements and calibration file names. No shell is involved so no injection was achieved (all 14 hostile strings x 5 fields rejected). | `pytest ... -k trailing_newline_is_rejected` (xfail strict) | Robotics (`fullmatch`) |
| VF-14 | minor | Provenance labelling | `summary.csv` of a MOCK session has no "MOCK FIXTURE" text (only `provenance=mock` and `score_source=mock_fixture` columns in every row). Banner is present in report.html, summary.md, summary.json, the three plots and `demo-summary.json`. The fault-injection report states "provenance=mock; not robot data" once. | `pytest tests/verification/test_reproducibility_and_reports.py -k mock_banner_text_also_in_csv` (xfail strict) | Eval |
| VF-15 | minor | Rubric vs code | `docs/evaluation-protocol.md` / scoring rubric: block must be entirely inside, "not touching or straddling the boundary". Code accepts touching: `corners_inside_square` uses `<=` (`sim_pybullet.py:142-143`). A block whose edge is exactly on the boundary scores success. Only the bottom face is tested, so a tilted block with an overhanging top is also accepted. Measure-zero in practice. | `sim_pybullet.py:136-144` | Robotics / Eval (pick one wording) |
| VF-16 | minor | Docs | README is the placeholder "(README is written at integration time.)". `docs/verification.md` and `docs/resume-evidence.md` are referenced as the home of measured values (`evaluation-protocol.md` section 6, `src/robotevalops/configs/targets.yaml`) but do not exist yet. | `ls docs` | Lead |
| VF-17 | minor | Hardware scope (documented) | `docs/hardware-setup.md` says parquet to `trace.jsonl` is not implemented. Consequence not stated: every hardware trial has a video but no trace, so once a QA hook is wired it gets `missing_artifact` ERROR and `recording_quality=fail`, i.e. zero hardware trials can ever be `evaluable`. | code read: `hardware_so101.run_episode` returns `RecordingSummary(video_relpath=...)` only | Robotics / Lead (state it) |

## 3. Attacks that FAILED to break the system (covered, all passing in `tests/verification/`)

Success evidence (V1)
- No-op controller: timeout, failure, lift 0. Gripper closes but never lifts: failure, `released False`.
- Block carried above the region and never released: block `all_corners_inside True`, `released False`, dwell max 0.0, failure.
- Block dropped straddling the edge (+0.05 m shift): `0 < in_target_fraction < 1`, failure.
- Dwell timer: reset by a single control step out of region (1.5 s, out, 1.5 s again does not succeed); success needs exactly 40 steps of 20 Hz; gripper commanded closed with block inside never accumulates dwell; block 5 mm inside the edge with centre inside is not success; 1 mm boundary and a 45-degree yaw handled by corner test (centre-only logic would pass them).
- `data/demo_sim`: 10 of 10 trials have strictly increasing timestamps, all state/action finite, no block jump greater than 0.15 m between rows (teleport detector), a block z rise (0.20 and 0.26 m), inside+open for the whole last 1.9 s of the trace, `dwell_s >= 2.0` in the DB; videos decode with frame count equal to trace rows (96 to 131), `fps 10`, frames change over time. Visual-condition trials are bit-identical in duration to nominal (expected for a state-based controller, as documented).
- The block is created once in `reset` and never repositioned in product code (grep of `sim_pybullet.py`); my dwell tests teleport it from the test only.

Lifecycle and accounting (V2)
- 6 illegal trial transitions, every transition out of every terminal state, wrong termination-reason for state, failed trial carrying an outcome: all rejected, nothing half-applied.
- Scoring PLANNED/RUNNING/FAILED/ABORTED trials rejected (4 termination reasons). Double score: `ScoreProtectionError`. Empty/whitespace reason on `edit_score` rejected, before/after audit stored. 8 threads x separate `EvalService` instances scoring one trial: exactly 1 ok, 7 `ScoreProtectionError`.
- Scripted none = autonomous; assisted and unknown = not; teleoperated + none + success = not; quality fail = not; unscored hand score defaults intervention to `unknown` = not.
- 8 planned trials, 3 attempted: manifest has 8 entries, metrics `planned 8 / attempted 3 / not_attempted 5`, per-condition and per-controller planned sums are 8.
- Hand-computed denominators on a 10-trial dataset (1 autonomous success, 1 quality-excluded success, 1 assisted, 1 failure, 1 unknown, 1 infra failure, 1 operator abort, 1 completed-unscored, 2 never attempted): planned 10, attempted 8, completed 6, failed 1, aborted 1, unscored 3, evaluable 4, autonomous 1, per-attempt 1/8, per-evaluable 1/4, intervention 1/8, infra 1/8 (operator abort not infra), recording pass 4/8, artifacts expected 16 missing 16; Wilson 95% bounds for 1/8 and 1/4 match my independent formula within 2e-3.
- Session gates: planned session cannot jump to running/completed/failed/ready; terminal session frozen (including `mark_preflight_passed`, `acknowledge_operator`); re-planning refused and trials survive; manual PREFLIGHT to READY does not clear `requires_fresh_preflight` and the Runner still refuses; stop request idempotent and prevents any trial while planned trials stay visible; hostile `register_artifacts` paths (8 variants) rejected; a tampered DB row with `../../secret.mp4` is refused by the dashboard resolver.
- Device lock exclusive, idempotent for owner, non-owner cannot release.

Crash recovery (V3), real process kill (`Popen.kill`, no cleanup) with a hanging mock adapter
- New `EvalService` sees session RUNNING and 1 RUNNING trial; `Runner` refuses the unrecovered session; `recover_interrupted` gives ABORTED/`interrupted_runner`, unscored, `duration_s` None, evidence note kept, trial directory bytes unchanged (sha256 of every file equal before and after), `trace.jsonl` registered; session PREFLIGHT with `requires_fresh_preflight`; recovery idempotent; Runner refuses until `mark_preflight_passed`; after preflight the interrupted trial is never re-run or resumed.
- Physical-session variant (mock adapter inside a physical session, to exercise gates only): no ack gives `HardwareRefusedError`, ack without preflight gives `PreflightFailedError`; after kill the device lock is still held (fail-safe) and is released only by `recover`; Runner refuses again until a fresh preflight.

Hardware safety (V4), `execute_argv` and tool discovery replaced by a recorder; real lerobot 0.4.4 exes are installed here and were never launched
- `robot teleop/record/rollout` refuse (non-zero exit, zero executions) for 12 combinations of missing/blank hardware-mode and ack; refuse when preflight fails (ports absent); refuse when joint calibration files are missing. Positive control (all gates satisfied and calibration present) executes exactly once and never executes calibrate, replay or setup-motors. `--dry-run` never executes.
- The CLI exposes no command containing calibrat/replay/setup/flash/motor. `calibrate` and `replay` builders refuse from the library without gate AND exact confirm token (4 variants each).
- `SO101HardwareAdapter.reset/run_episode` refuse without mode, without ack, with blank operator, with an ack for another session (when a session id is set), without preflight on that instance, after a failed preflight. `run_episode` returns `task_success=None`.
- `session run` on a physical session: refused without ack, refused in PLANNED without preflight, no tool launched when hardware mode env is unset (see VF-08).
- 14 injection strings x 5 identifier/port/repo fields rejected; camera path/name injection (`}`, `,`, spaces, newline) rejected; task text with `--dataset.push_to_hub=true; echo hi && 'x'` stays a single argv element and `push_to_hub=false` is still passed exactly once.
- Static grep over `src/` and `scripts/` for `shell=True`, `os.system`, `os.popen`, `eval(`, `exec(`, `pickle`, `yaml.load(`: no hits. Only subprocess uses: `lerobot_wrapper.execute_argv` (list argv, `shell=False`, `stdin=DEVNULL`), `util.git_commit` (fixed list), `report_cmds.dashboard` (list).
- Auto-calibration guard: read `lerobot/robots/so_follower/so_follower.py` 0.4.4. `connect()` calls `calibrate()` when the file is missing OR when motor values mismatch the file. The wrapper only checks file existence, but stdin is `DEVNULL`, so the first `input()` in the mismatch case raises `EOFError` before any register is written. The missing-file case would call `disable_torque()` before its first `input()`, so the existence guard is load-bearing and works. Not executed against hardware.

Storage and QA (V5)
- 15 hostile store keys (`../`, absolute, drive letters, backslash, `.meta`, empty, `a//b`, NUL) rejected, nothing written. Windows junction inside the store (put and get through it) and inside a run dir (collect/upload) did not escape or leak `secret.txt` (symlink tests in `tests/data` are skipped here, junctions exercised instead).
- Credential names blocked: see VF-10 for the complement.
- Overwrite with different bytes refused and the original is intact; identical re-upload skipped; caller hash that does not match the file refused; injected `fsync` failure leaves no final file, no sidecar, no tmp file.
- `verify` re-reads bytes: same-size tamper with a lying sidecar is caught as MISMATCH; `verify_run` marks tampered and deleted objects (agreement 0.5, FAILED) and S3 `verify` code path recomputes SHA-256 and never uses the ETag (code read; moto tests are labelled `test_mocked_s3_*` with a docstring disclaimer; no real S3 was used).
- Retry: exactly `max_attempts` calls, sleeps `[1,2,3,3]` (capped), non-retryable error propagates with no sleep, total timeout bounds the loop, late success after the per-call timeout is a timeout.
- QA on real H.264 files: truncation at 0, 1, 25, 50, 90 and 96 percent of bytes and by 100 bytes: FAIL (`truncated_video` or `undecodable_frames`); file of random bytes containing the word "moov": FAIL `undecodable_frames`; video with fewer frames than trace rows: FAIL `truncated_video`. Losing only the last 1 to 50 bytes of the container still decodes all 40 frames and passes; that is not frame loss and the hash check would flag it if the hash was recorded before. NaN, `Infinity`, `-Infinity`, bare `NaN` token, decreasing `t`, extra state column, missing action column, missing `t`, `schema_version` 2.0, missing `schema_version`, garbage JSON line, missing header: each detected with the right code and `quality=fail`, `accepted=False`. Missing video and trace: FAIL. Whitespace-only change after hashing: `hash_mismatch`. Duplicate trial ids in a manifest: ERROR. Quarantine copies, never deletes (every file in the run dir has the same sha256 before and after, repeat is safe) and refuses a `../escape.txt` relpath.

Reproducibility (V7)
- Two full sim runs (2 controllers x {nominal, object_position} x 2 trials, seed 4242, render off): schedule exact, outcomes, termination reasons and `applied_condition` identical, block final pose within 1e-3 m, durations equal; across controllers each cell has the same seed and the same applied block offset (pairing) and offsets are within the 0.04 m bound and re-drawn per trial index; adding or removing a controller does not change seeds; a different base seed changes all seeds.

Claims audit (V6), checked against code and generated files
- Sim summary and html state Panda not SO-101, scripted not learned, state-based controllers unaffected by visual conditions, small n, p-values not significance. McNemar is reported as "n/a" when no discordant pairs. No SO-101 or hardware performance claim, no learned-policy claim found. `hardware-setup.md` opens with "Nothing in this repository has been verified on real hardware"; its lerobot 0.4.4 facts check out against the installed package (no `lerobot-rollout`, so101 modules present, entry points present). Its sim table (5/5 per cell, lift >= 0.19 m) is consistent with the 10 demo trials; the 50-run claim itself was not re-run.
- Mock banner present in report.html, summary.md, summary.json, demo-summary.json and all three plots (image inspected) for mock sessions; absent in summary.csv (VF-14). The fault report is labelled synthetic mock fixtures.
- "10 of 10 passed" in `docs/fault-injection-report.md` is a statement about QA reports, quarantine and recovery on synthetic fixtures; "misleading success prevented" there means QA quality fail and not accepted, not that the metrics pipeline excludes it (see VF-13b).

## 4. Commands run and results

```
# 1) full suite (before my additions; run in parallel with my work)
.venv/Scripts/python.exe -m pytest -q -x -p no:cacheprovider
  -> 439 passed, 4 skipped in 232.87s   (skips: 2 symlink tests, 1 real-S3, 1 dashboard symlink)

# 2) my tests only
.venv/Scripts/python.exe -m pytest tests/verification -q -p no:cacheprovider
  -> 235 passed, 16 xfailed in 98.31s   (xfail = the 16 strict markers for VF-01..VF-14; VF-09 is 3 parametrised cases)

# 2b) full suite again including tests/verification (final state)
.venv/Scripts/python.exe -m pytest -q -x -p no:cacheprovider
  -> 674 passed, 4 skipped, 16 xfailed in 283.97s (exit 0)

# 3) lint / types
.venv/Scripts/python.exe -m ruff check .          -> 8 errors, all in src/robotevalops/cli/demo_cmds.py and src/robotevalops/integration.py (VF-18)
.venv/Scripts/python.exe -m ruff format --check .  -> 1 file would be reformatted (src/robotevalops/cli/demo_cmds.py)
.venv/Scripts/python.exe -m mypy src               -> Success: no issues found in 67 source files
.venv/Scripts/python.exe -m ruff check tests/verification && ruff format --check tests/verification -> clean

# 4) selected manual probes (outputs quoted in the findings)
direct adapter runs: noop / close_no_lift / hold_never_release / straddle / pusher / dwell_required_s=0,-1
DB audit of data/demo_sim and data/demo (read-only sqlite) + cv2 decode of every demo_sim video
robotevalops robot lerobot-info --json ; grep of installed lerobot so_follower.py
.venv/Scripts/python.exe /tmp/chk.py   (CLI chain session run -> truncate videos -> data validate -> report metrics)
```

Environment notes: nothing under `data/` was written (all work in pytest `tmp_path` or system temp); `data/demo`
and `data/demo_sim` were opened read-only. The fault-injection report and demo reports were not regenerated.

## 5. Files added (all under `tests/verification/`)

`sim_helpers.py`, `qa_helpers.py` (independent synthetic fixture builder), `test_sim_success_audit.py`,
`test_lifecycle_accounting.py`, `test_session_gates.py`, `test_crash_recovery.py`, `test_hardware_safety.py`,
`test_storage_qa.py`, `test_reproducibility_and_reports.py`, `conftest.py`, `__init__.py`.
