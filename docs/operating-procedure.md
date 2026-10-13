# Operating procedure (Robot Wrangler)

For the person who runs tests, resets the scene and collects data. Commands below follow `robotevalops <group> --help`;
check `--help` on your build if a flag differs. Everything runs from a Linux (or any) shell with the repo's
environment. Set the data home once: `export ROBOTEVALOPS_HOME=/path/to/data` (or pass `--home`).

## Safety first

- Hardware motion needs explicit hardware mode, a per-session operator acknowledgement and a passing preflight. Do
  not skip any of them.
- A software stop request is **not** an emergency stop. Keep the physical e-stop/power cut within reach at all times.
- Never leave the arm moving unattended. Never use LLM-generated actions to drive the robot.
- Never edit recorded files by hand. Scores change only through `report score` / `report edit-score`.

## 1. Start a test from Linux

```bash
robotevalops session create --name pick_place_run1 --provenance physical_hardware --backend so101_lerobot \
    --operator "<your name>" --device-id <device> --calibration-ref <calibration file> --config <eval.yaml> --json
robotevalops session plan <session_id> --config <eval.yaml>
robotevalops session preflight <session_id>
robotevalops session ack <session_id> --operator "<your name>"      # hardware only
robotevalops session run <session_id> --max-trials 5
```

For simulation use `--provenance simulation --backend pybullet_panda`; no acknowledgement is needed. If a run is
interrupted, restart the preflight (`session recover`, then `session preflight`) before running again; interrupted
trials stay `aborted` with their evidence.

To stop: `robotevalops session stop <session_id>` (a software request; use the physical e-stop in an emergency).

## 2. Reset the scene (every trial)

Use `docs/templates/reset-checklist.md`. In short: robot to the home pose, block on the start mark, target region
clear and visible, camera running with the lighting that matches the condition, nothing else in the workspace.
Time the reset with a stopwatch and write it in `docs/templates/reset-time-log.csv`. Do not touch the block after a
trial has started; any touch during a trial makes it an assisted trial.

## 3. Record success or failure

- Simulation/mock: scored automatically from recorded state.
- Hardware/imported: watch `trials/<trial_id>/video.mp4` against `docs/templates/scoring-rubric.md`, then:

```bash
robotevalops report unscored <session_id>
robotevalops report score <trial_id> --outcome success|failure --scorer "<name>" --intervention none|assisted
```

Fix a wrong score with `report edit-score ... --editor "<name>" --reason "<why>"`. The old and new values and your
reason are logged. Report problems with `docs/templates/bug-report-template.md`.

## 4. Collect demonstrations

```bash
robotevalops robot teleop --config <config> --hardware-mode --ack-operator "<your name>" --dry-run   # rehearse first
robotevalops robot record --config <config> --episodes 5 --hardware-mode --ack-operator "<your name>"
```

Only accept demonstrations that meet the acceptance checklist (Data/storage owns it under `docs/templates/`).
Failed or flagged demonstrations are kept and quarantined, not deleted.

## 5. Check recordings

```bash
robotevalops data validate runs/<session_id>
```

Each trial needs `video.mp4`, `trace.jsonl` and a log. Fix or flag anything the check reports (missing or truncated
video, non-monotonic timestamps, non-finite values). Open the dashboard to look at videos and QA flags:

```bash
robotevalops report dashboard --home "$ROBOTEVALOPS_HOME"
```

## 6. Transfer artifacts

```bash
robotevalops data package runs/<session_id> --session-id <session_id>
robotevalops data upload runs/<session_id> --session-id <session_id> --store local --store-root <dest>
robotevalops data verify runs/<session_id> --session-id <session_id> --store local --store-root <dest>
```

An upload counts as complete only after `verify` recomputes the SHA-256 and it matches. A mismatch or timeout is
reported, never ignored.

## 7. Report

```bash
robotevalops report metrics <session_id>
robotevalops report export <session_id>        # summary.md/csv/json, plots, report.html under <home>/reports/<session_id>/
```

Read the warnings (small n, unscored, never-attempted, missing artifacts) before quoting any number. Quote the
session id, provenance and denominator with every figure.
