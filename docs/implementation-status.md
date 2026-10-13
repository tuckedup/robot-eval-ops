# Implementation status ledger

Orchestration mode: **native parallel subagents** (Agent Teams not enabled in this environment; checked
`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` unset, Claude Code 2.1.296). Max 3 workers concurrently. Role definitions in `.claude/agents/`.
Subagent tool access is by `tools:` allowlist; ownership is enforced by instruction and lead inspection of handoffs.

| ID | Task | Owner | Depends | Status | Acceptance evidence | Blockers |
|---|---|---|---|---|---|---|
| L1 | Inspect env (py3.11 venv, pybullet+Panda+TinyRenderer verified) | lead | - | done | pybullet 3.2.7 built, Panda loads, 64x64 render ok | - |
| L2 | Shared contracts, pyproject, CLI skeleton, agents | lead | L1 | done | docs/contracts.md | - |
| C1 | Core: DB + EvalService + scheduler + lifecycle | core | L2 | in progress (dispatched) | | |
| C2 | Core: Runner + recovery + device lock + F10 | core | C1,R1 | pending | | |
| R1 | Robotics: mock adapter + conditions + registry | robotics | L2 | in progress (dispatched) | | |
| R2 | Robotics: PyBullet Panda sim + scripted controllers | robotics | R1 | pending | | |
| R3 | Robotics: LeRobot wrappers + hardware adapter/preflight | robotics | R1 | pending | | |
| D1 | Data: recording writers + QA + quarantine | data | L2 | in progress (dispatched) | | |
| D2 | Data: local/S3 stores + packaging + retry | data | L2 | pending | | |
| D3 | Data: faults F01-F09 + report + data CLI | data | D1,D2 | pending | | |
| E1 | Eval: metrics + Wilson + scoring + exports | eval | C1 | pending | | |
| E2 | Eval: dashboard + html report + docs | eval | E1 | pending | | |
| V1 | Verifier: adversarial review + acceptance | verifier | all | pending | | |
| L3 | Integration, demo script, CI, Dockerfile, README, verification doc | lead | all | pending | | |
