# RobotEvalOps

**Reproducible robot-policy evaluation, teleoperation data QA, and experiment artifact management.**

RobotEvalOps is the "Robot Wrangler" workflow as software: plan a paired test schedule, run trials through a
persisted lifecycle, record video and state/action traces, score outcomes with an audit trail, QA the recordings,
move artifacts with SHA-256 verification, and report honest numbers (denominators, Wilson intervals, failures kept).

> **Status in one paragraph.** Everything runs offline on CPU. A deterministic **mock fixture** exercises the
> workflow and fault paths (it is never robotics evidence). A real **PyBullet Panda** pick-and-place simulation
> produces physics-derived outcomes. An **SO-101 / LeRobot** pathway exists but has **only been tested with fake
> executables**: no robot was operated, nothing was calibrated, no learned policy was trained. See
> [Limitations](#limitations) and [docs/verification.md](docs/verification.md).

## Architecture

```
            +-------------------+      +-------------------------------+
 Operator → |  Typer CLI        | ───→ |  EvalService (core/service)   |  ← public API only
            |  session/robot/   |      |  SQLite: sessions, trials,    |      ┌──────────────────┐
            |  data/report/demo |      |  score_edits, locks, events   | ←─── | Streamlit        |
            +---------┬---------+      +--------------┬----------------+      | dashboard (read  |
                      │                               │                       | + audited scoring)|
                      ▼                               ▼                       └──────────────────┘
              +---------------+  one Runner owns   +------------------+
              |   Runner      |  device control    | metrics/reporting|  Wilson CIs, denominators,
              | (core/runner) |                    | md/csv/json/html |  comparisons, failures
              +-------┬-------+                    +------------------+
          adapter interface (adapters/base.py)
     ┌───────────────┼───────────────────────┐
     ▼               ▼                       ▼
  MockAdapter   PyBulletPandaAdapter   SO101HardwareAdapter ── lerobot subprocess (argument lists)
  (fixture)     (physics, CPU)         (refuses without hardware mode + ack + preflight)
     └──────┬────────┴──────────────┬────────┘
            ▼                       ▼
   recording (video.mp4 + trace.jsonl)  →  qa (checks, quarantine copies)  →  storage (local | S3, SHA-256)
```

Claude agents *built* this repository (see `.claude/agents/`, [docs/implementation-status.md](docs/implementation-status.md));
RobotEvalOps itself is deterministic and no LLM output ever drives robot motion.

## Install

Python 3.11 (3.11.16 tested) and [uv](https://docs.astral.sh/uv/):

```bash
uv sync --extra sim --extra dashboard --extra s3 --extra dev --python 3.11
uv run robotevalops --help
```

Extras: `sim` (PyBullet), `dashboard` (Streamlit), `s3` (boto3), `lerobot` (optional, heavy, hardware pathway),
`dev` (pytest, ruff, mypy, moto). PyBullet may compile from source on some platforms (needs a C++ toolchain).

## Quickstart (commands below were executed; see docs/verification.md)

```bash
# 1) One command: plan -> run -> QA -> package/upload/verify -> reports -> 10 fault cases   (~15 s, MOCK fixture)
uv run robotevalops demo run --home data/demo

# 2) Same pipeline on real PyBullet Panda physics (10 trials, ~2.5 min on CPU)
uv run robotevalops demo run --backend sim --home data/demo_sim --skip-faults

# 3) Dashboard (ROBOTEVALOPS_HOME selects the data root)
ROBOTEVALOPS_HOME=data/demo uv run streamlit run src/robotevalops/dashboard/app.py     # PowerShell: $env:ROBOTEVALOPS_HOME="data/demo"

# 4) Tests (offline, CPU; no credentials, robot or paid API)
uv run pytest -m "not physics and not s3_real and not hardware"
uv run pytest -m physics                                   # separate small physics smoke
uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

`demo run` prints the report paths (`data/demo/reports/<session_id>/report.html`, `summary.{md,csv,json}`,
`fault-injection-report.{md,json}`). Pre-generated copies are in [docs/demo/](docs/demo) and
[docs/fault-injection-report.md](docs/fault-injection-report.md).

The full evaluation template (2 controllers × 5 conditions × 10 trials = 100 planned trials):

```bash
uv run robotevalops demo run --backend sim --config src/robotevalops/configs/eval_full_sim.yaml --home data/full_sim --skip-faults   # ~20-25 min CPU
```

Step-by-step CLI (what `demo run` chains): `session create/plan/run/recover/stop/export-manifest`,
`data validate/quarantine/package/upload/verify/faults`, `report score/edit-score/metrics/compare/export`.
See [docs/operating-procedure.md](docs/operating-procedure.md).

## What the simulation demo measures

Task (rubric-v1): pick the block, place it with all corners strictly inside the target region, release, and keep it
there 2.0 s within a 30 s attempt. Success is computed from simulator state (grasp contacts, lift, region
containment, gripper release, dwell), never from a flag, and the block is never teleported. Two versioned scripted
controllers (`scripted_baseline_a/b`, IK + real gripper contact) are compared over five conditions (nominal, object
position, lighting, background, partial occlusion) with identical seeds per cell (paired).

Measured in this repository (Windows 11, Python 3.11.16, PyBullet 3.2.7, CPU), full template, run on the final code
([docs/demo/sim-full-100/summary.md](docs/demo/sim-full-100/summary.md)): **100 planned / 100 attempted / 100 completed /
0 failed / 0 aborted / 0 unscored; autonomous success 100/100 (Wilson 95% [0.963, 1.000])**, recording QA pass
100/100, 300/300 artifacts present and SHA-256-verified after a local-store round trip. Mean trial duration 11.3 s
(n=100, simulated time), block lifted 0.20–0.26 m in every trial.

**How to read that number.** It is a *scripted, state-based controller in a deterministic simulator*. Perfect
success is expected and says nothing about learned-policy performance, camera robustness (lighting, background and
occlusion only change rendered pixels the controller does not read), the SO-101, or real-world reliability. The
paired comparison has zero discordant pairs, so there is nothing to test.

## Fault injection (ten deterministic cases)

Missing video, truncated video, non-monotonic timestamps, non-finite action, wrong schema, missing model artifact,
duplicate trial id, hash mismatch, transfer timeout, interrupted runner. Each is built from real bad files/states,
must be detected with an actionable message, must preserve evidence, and must not end as a success. Last executed
result: **10/10 executed, 10/10 passed** ([docs/fault-injection-report.md](docs/fault-injection-report.md)). These
use synthetic mock fixtures and mocked storage — they test the detectors, not real robots or real AWS.

## Hardware pathway (SO-101 + LeRobot) — not hardware-verified

Config template `src/robotevalops/configs/hardware/so101.example.yaml`, wrapper `adapters/lerobot_wrapper.py`, adapter
`adapters/hardware_so101.py`, operator guide [docs/hardware-setup.md](docs/hardware-setup.md). Safety posture:
nothing moves, calibrates, flashes or replays during install or CI; motion needs explicit hardware mode, a
per-session operator acknowledgement and a passing non-moving preflight; the wrapper refuses to launch
`lerobot-teleoperate`/`record` unless calibration files already exist (LeRobot otherwise starts calibration by
itself); commands are argument lists, never shell strings. A software stop request is not an emergency stop.
Tested LeRobot: 0.4.4 (installed here; wrappers exercised with **fake executables only**). Authoritative docs:
<https://huggingface.co/docs/lerobot/so101>, <https://huggingface.co/docs/lerobot/il_robots>,
<https://huggingface.co/docs/lerobot/index>.

## Storage

Local store by default (offline, atomic writes, SHA-256 index). Optional S3 (`--store s3`) uses the normal AWS
credential chain, never creates buckets or touches IAM, verifies by downloading and recomputing SHA-256 (not ETags).
Example commands for a user-owned bucket: [docs/storage-aws.md](docs/storage-aws.md). S3 behaviour has only been
tested against a mock (moto); real-AWS verification is an opt-in test (`ROBOTEVALOPS_S3_BUCKET`, `-m s3_real`).

## Docs

[contracts](docs/contracts.md) · [architecture](docs/architecture.md) · [data schema](docs/data-schema.md) ·
[evaluation protocol](docs/evaluation-protocol.md) · [operating procedure](docs/operating-procedure.md) ·
[hardware setup](docs/hardware-setup.md) · [troubleshooting](docs/troubleshooting.md) ·
[verification](docs/verification.md) · [independent findings](docs/verification-findings.md) ·
[resume evidence](docs/resume-evidence.md) · [90-second operator demo](docs/walkthrough-90s.md) ·
[audit remediation](docs/audit-remediation.md) · [LeRobot datasets + QA](docs/lerobot-datasets.md) ·
[stress study](docs/stress-study/README.md) · [paired duration analysis](docs/analysis/paired_duration_full_sim/analysis.md) ·
[independent re-audit](docs/verification-reaudit.md) · [current checkpoint status](docs/checkpoint.md) ·
templates in [docs/templates/](docs/templates) · proposed targets in `src/robotevalops/configs/targets.yaml` (goals, not results).

## Added after the independent audit

```bash
robotevalops demo operator                         # ~2 min: preflight, success, physics failure, corrupt recording rejected, interrupted+recovered run, verified transfer, report
robotevalops robot import-dataset --path <lerobot-dir> --out <dir> --source-revision <rev> --license <lic>   # v2.1/v3 content QA + split + provenance record
robotevalops report paired-duration --a <ctrl> --b <ctrl> --home <home> --out <dir>                          # paired analysis (read-only on the source data)
robotevalops study pilot|freeze|run|report ...     # pre-specified, frozen physics stress study (docs/stress-study/README.md)
scripts/verify_all.sh                              # regenerates docs/verification-run.json from the current commit
scripts/verify_wheel.sh                            # non-editable wheel in a fresh venv, demo from an unrelated directory
```

Default YAML configs ship inside the package (`robotevalops/configs`). Docker: the Dockerfile uses `uv sync --locked`;
the image build was **not** executed (no running Docker daemon). Supported/tested: Python 3.11, Windows, lerobot 0.4.4.

## Limitations

- No physical robot was operated; no demonstrations were collected; no learned (ACT) policy was trained
  (documented workflow, unexecuted). Panda scripted traces are not valid SO-101 data.
- Simulation success reflects a scripted state-based controller; mock results are fixtures only.
- Scoring-agreement and reset-time-improvement targets need independent human measurements (templates provided; no data).
- Real-AWS transfers, real LeRobot datasets, and hardware video scoring are unexercised.
- Windows file-symlink escape tests are skipped on accounts that cannot create symlinks (directory junctions were tested).
- No screenshots were captured.
- Targets in `src/robotevalops/configs/targets.yaml` (60 demos / 3 sessions, 100 trials, ≥95% demo QA acceptance, …) are proposals.
  Only the 100-trial simulation template and the ten fault cases have been executed here.
- License: not chosen (needs the owner's decision).

Suggested repository description: *Reproducible robot-policy evaluation, teleoperation data QA, and experiment artifact management.*
