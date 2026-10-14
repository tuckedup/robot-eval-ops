# Verification record

> **Superseded counts.** The test totals in sections 3-4 below (578/53/745) describe commit `095ffb0` and did not
> reproduce at that commit (audit reruns: 691 offline passed, 43 physics passed). Current, machine-generated results
> (commit, versions, per-directory outcomes, skip reasons) are in `docs/verification-run.json`, produced by
> `scripts/verify_all.sh`. Audit findings and fixes: `docs/audit-remediation.md`. The simulation numbers in section 4
> are unchanged original acceptance evidence.

Everything here was executed in this repository's environment on 2026-10-13. Nothing is claimed beyond what is listed.
Software test outcomes, mock fixtures, physics results, imported-dataset QA, hardware results and proposed targets are
kept in separate sections.

## 1. Platform and versions

Windows 11 Home 10.0.26220 · CPython 3.11.16 (uv-managed venv) · robotevalops 0.1.0 · numpy 2.2.6 · pandas 3.0.6 ·
pydantic 2.14.1 · pybullet 3.2.7 (built from source, MSVC) · opencv-python-headless 4.12.0.88 · streamlit 1.65.0 ·
boto3 1.43.112 · moto 5.2.4 · lerobot 0.4.4 and torch 2.10.0 (installed only in the development venv; **not** part of the
clean-clone install). No GPU, no robot, no AWS credentials, no paid API were used.

## 2. Orchestration

Claude Code 2.1.296. Agent Teams was not enabled, so development used **native parallel subagents** (at most three
active at once): core, robotics, data/storage, evaluation/reporting engineers; then an independent verifier that did not
write the code it reviewed. Role files: `.claude/agents/`. Task ledger: `docs/implementation-status.md`. The lead owned
shared contracts, integration and the final fixes. Subagent tool access was an allowlist; file ownership was enforced by
instruction and by lead inspection of each handoff, not by sandbox isolation (no git worktrees were used).

## 3. Clean-environment reproduction (fresh `git clone` into a new directory, then the README commands)

| Check | Command | Result |
|---|---|---|
| Install | `uv sync --extra sim --extra dashboard --extra s3 --extra dev --python 3.11` | ok, 2m43s (PyBullet wheel was in the uv cache) |
| CLI help / version | `uv run robotevalops --help`, `version` | ok, prints `0.1.0` |
| Mock demo | `uv run robotevalops demo run --home data/demo` | ok, 21 s; 12 + 4 planned trials, QA, upload+verify, reports, 10 fault cases |
| Sim demo | `uv run robotevalops demo run --backend sim --home data/demo_sim --skip-faults` | ok, 142 s; 10/10 attempted, 10/10 autonomous success |
| Lint / format / types | `ruff check .`, `ruff format --check .`, `mypy src` | clean (127 files / 67 source files) |
| Offline tests | `pytest -m "not physics and not s3_real and not hardware"` | **578 passed, 1 skipped** |
| Physics smoke | `pytest -m physics` | **53 passed** |
| Hardware refusal | `robotevalops robot teleop` / `... --hardware-mode` | exit 2 both times: needs `--hardware-mode`, then `--ack-operator` |
| Dashboard | `streamlit run src/robotevalops/dashboard/app.py --server.headless true` against the demo data | `/_stcore/health` = `ok`, `/` = HTTP 200; report/summary paths exist |

The first clean-clone run found one real bug that the development venv hid: with LeRobot absent, the hardware CLI
reported "lerobot-teleoperate not found" before checking the hardware-mode/ack gates (still a refusal, exit 2). Gates now
run first; `test_cli_refuses_without_hardware_mode_and_ack` passes in the clean clone.

Full development-tree suite before that fix (all markers except `s3_real`): **745 passed, 4 skipped, 0 failed, 0 xfailed**
(~5 min), plus `ruff`/`mypy` clean.

## 4. Simulation (PyBullet Panda) — physics results

Full template `src/robotevalops/configs/eval_full_sim.yaml` (2 scripted controllers × 5 conditions × 10 trials), run on the final code:
planned 100 / attempted 100 / completed 100 / failed 0 / aborted 0 / unscored 0; autonomous success 100/100,
Wilson 95% [0.963, 1.000]; recording-QA pass 100/100; artifacts 300/300 present and SHA-256-verified through the local
store; mean trial duration 11.31 s (median 11.53, min 9.35, max 13.95; simulated time, n=100); mean reset 0.26 s; block
lift 0.20–0.26 m in every trial; minimum measured dwell 2.000 s. Source: `docs/demo/sim-full-100/` (summary.md/csv/json,
report.html). Reproducibility (independent verifier, two runs with the same seeds): identical schedules, outcomes and
termination reasons; final block pose within 1e-3 m.

Interpretation limits: scripted state-based controllers in a deterministic simulator; 100% is expected and is not
evidence of learned-policy, visual, SO-101 or real-world performance. Lighting/background/occlusion change only rendered
pixels the controller never reads. Paired comparison: 50 pairs, zero discordant, so no test is possible.

Earlier, before the verifier's VF-01 finding made grasp+lift mandatory for success, the same template also completed
100/100 on the previous rule; that run was discarded and re-run, and is not reported anywhere else.

## 5. Mock fixture results (never robotics performance)

`demo run` (mock): 12 planned, 12 completed, 9 mock-fixture successes; second mock session with an injected recording
failure: 4 planned, 3 attempted, 3 infra-failed (unscored), 1 never attempted — all remain in the denominators
(`docs/demo/mock*/`). Every mock output carries the "MOCK FIXTURE - not evidence of robotics performance" banner
(html, md, json, csv column, plots).

## 6. Fault injection (synthetic mock fixtures, mocked storage)

`robotevalops data faults` (run inside `demo run`): **10/10 executed, 10/10 passed** — missing video, truncated video,
non-monotonic timestamps, non-finite action, wrong schema, missing model artifact, duplicate trial id, hash mismatch,
transfer timeout, interrupted runner. A case passes only if detected, evidence preserved (source bytes unchanged), and a
misleading success prevented. Report: `docs/fault-injection-report.md` / `.json`.

## 7. Independent adversarial review

`docs/verification-findings.md`: 19 findings (1 blocker, 5 major, 13 minor). The blocker: `session run`/`data validate`
did not feed recording QA into the database, so a corrupted recording could still be counted as an autonomous success
outside `demo run`. All 19 were addressed (shared QA hooks in `integration.py`, grasp-and-lift required for simulation
success, dwell/timeout validation, zero-row trace rejected, store re-hashing instead of trusting sidecars, broader
credential screening, gate-refusal accounting, hardening, docs). Each reproducible defect became a strict-xfail test and
is now an ordinary passing regression test under `tests/verification/`. The fixes were validated by the test suite, not by
a second independent review.

## 8. Skipped or not executed (explicit)

- **Real hardware:** no SO-101, no calibration, no teleoperation, no recording, no rollout. Wrappers were tested only with
  fake executables/fixtures. Real LeRobot dataset import/QA: no real dataset was available (QA is tested on a synthetic
  LeRobot-style directory labelled synthetic).
- **ACT training / any learned policy:** not executed (documented workflow in `docs/hardware-setup.md`).
- **Real AWS S3:** not executed (`-m s3_real`, needs `ROBOTEVALOPS_S3_BUCKET`); moto-mocked tests only.
- **GitHub Actions workflow** (`.github/workflows/ci.yml`) and **Dockerfile:** written, not run (no remote, Docker not exercised).
- **Human measurements:** scoring agreement and reset-time improvement — templates only, no data.
- **Targets** (`src/robotevalops/configs/targets.yaml`): 60 demonstrations/3 sessions not attempted (no hardware, no fake demos);
  100 evaluation trials executed in simulation only; 10 fault cases detected 10/10; checksum agreement 300/300 for the
  local-store round trip (not S3); required-metadata completeness is computed per manifest by the code, but no hardware
  manifests exist.
- Windows file-symlink escape tests skipped (account cannot create symlinks); directory-junction escape was tested.
- `mypy` was run on `src`, not on tests. No screenshots captured. No license chosen.

## 9. Known limitations / blockers

No blockers for the feasible path. Open items need owner action: hardware, a real dataset, an AWS bucket, human scorers,
and a license decision.
