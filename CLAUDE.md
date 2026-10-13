# RobotEvalOps — project guide for Claude Code

Reproducible robot-policy evaluation, teleoperation data QA, and experiment artifact management.
Python 3.11, src layout (`src/robotevalops`), Typer CLI, Pydantic, SQLite, optional boto3/PyBullet/Streamlit.

## Commands
- Env: `uv sync --all-extras` (venv in `.venv`); run via `.venv/Scripts/python.exe -m ...` on Windows.
- Tests (offline, CPU): `pytest -m "not physics and not s3_real and not hardware"`; physics smoke: `pytest -m physics`
- Lint/types: `ruff check . && ruff format --check . && mypy src`
- CLI: `robotevalops --help`; demo: `robotevalops demo run`; dashboard: `streamlit run src/robotevalops/dashboard/app.py`

## Architecture (see docs/architecture.md, docs/contracts.md)
core (SQLite service, lifecycle, runner) -> adapters (mock | pybullet sim | hardware/LeRobot) -> recording/qa
-> storage (local | s3) -> metrics/reporting/dashboard. Dashboard/reporting use `core.service.EvalService` only.
Claude agents BUILD this software; RobotEvalOps itself is deterministic. No LLM output ever drives robot motion.

## Provenance rules (non-negotiable)
- Provenance: mock | simulation | imported_real_recording | physical_hardware. Controller type is separate:
  scripted | learned | teleoperated. A scripted config is not a learned checkpoint.
- Mock results are never performance evidence. Panda sim is not SO-101. Never claim hardware ran unless it did.
- Never fabricate rollouts, success flags, timestamps, states, demonstrations, human measurements or metrics.
- Hardware motion needs explicit hardware mode + per-session operator ack + passing configured preflight. Never
  auto-move/calibrate/flash/replay in install or CI. Software stop request != emergency stop.
- Do not weaken checks to make results look good. Report failures and incomplete runs.

## File ownership
See docs/contracts.md §1. Workers edit only their subtree; shared contracts change via the lead.
Task ledger: docs/implementation-status.md. Agents: .claude/agents/*.md.
