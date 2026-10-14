# Implementation status ledger

Orchestration mode: **native parallel subagents** (Agent Teams not enabled in this environment; checked
`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` unset, Claude Code 2.1.296). Max 3 workers concurrently. Role definitions in `.claude/agents/`.
Subagent tool access is by `tools:` allowlist; ownership is enforced by instruction and lead inspection of handoffs.

| ID | Task | Owner | Depends | Status | Acceptance evidence | Blockers |
|---|---|---|---|---|---|---|
| L1 | Inspect env (py3.11 venv, pybullet+Panda+TinyRenderer verified) | lead | - | done | pybullet 3.2.7 built, Panda loads, render ok | - |
| L2 | Shared contracts, pyproject, CLI skeleton, agents | lead | L1 | done | docs/contracts.md | - |
| C1 | Core: DB + EvalService + scheduler + lifecycle | core | L2 | done | tests/core 196 pass | - |
| C2 | Core: Runner + recovery + device lock + F10 | core | C1,R1 | done | F10 passes; crash-recovery tests (incl. verifier real process kill) | - |
| R1 | Robotics: mock adapter + conditions + registry | robotics | L2 | done | tests/robotics | - |
| R2 | Robotics: PyBullet Panda sim + scripted controllers | robotics | R1 | done | 100/100 sim run; physics tests 53 pass | - |
| R3 | Robotics: LeRobot wrappers + hardware adapter/preflight | robotics | R1 | done (fake executables only) | gates refuse; no hardware verification | no hardware |
| D1 | Data: recording writers + QA + quarantine | data | L2 | done | tests/data | - |
| D2 | Data: local/S3 stores + packaging + retry | data | L2 | done (S3 via moto only) | 300/300 checksums local | no AWS |
| D3 | Data: faults F01-F09 + report + data CLI | data | D1,D2 | done | docs/fault-injection-report.md 10/10 | - |
| E1 | Eval: metrics + Wilson + scoring + exports | eval | C1 | done | tests/eval | - |
| E2 | Eval: dashboard + html report + docs | eval | E1 | done | dashboard health ok, AppTest | no screenshots |
| V1 | Verifier: adversarial review | verifier | all | done | docs/verification-findings.md (19 findings) | - |
| F1 | Fix round: VF-01..VF-18 (core, robotics, data, eval, lead) | all | V1 | done | strict-xfail tests now pass; 745 pass | - |
| L3 | Integration, demo, CI, Docker, README, verification doc | lead | all | done (CI + Docker written, not run) | docs/verification.md | no remote / Docker not run |

Lead-made edits to worker-owned files (to keep ownership honest): `tests/verification/` assertions updated for fixed behaviour
(VF-02, VF-08, VF-11); `cli/robot_cmds.py` gate-before-discovery reorder found by the clean-clone run.

## Reopened after the independent audit (see `docs/audit-remediation.md`)

| ID | Task | Status | Evidence |
|---|---|---|---|
| A1 | QA fails closed (error state, verified-success rule) | done | `tests/core/test_qa_fail_closed.py` |
| A2/A3 | Dataset QA substance + LeRobot v3/v2.1 support, real public dataset | done | `tests/data/test_dataset_import.py`, `docs/real-data/` |
| A4 | Calibration content check + no-auto-calibration guard (fake buses) | done | `tests/robotics/test_hardware_guard.py` |
| A5 | Wheel ships configs; Docker uses lock | done / Docker build NOT executed (daemon not running) | `tests/verification/test_packaging.py` |
| A6 | Durable sessions + physical-port lease for hardware CLI | done | `tests/robotics/test_hardware_lease.py` |
| A7/A8 | Consecutive grasp contact; identity-keyed grouping and pairing | done | `tests/robotics/test_grasp_contact_rule.py`, `tests/eval/test_identity_pooling.py` |
| X1 | Paired duration analysis | done | `docs/analysis/paired_duration_full_sim/` |
| X2 | Frozen failure-oriented stress study | done | `docs/stress-study/results_stress_v1/` |
| X3 | Operator demo | done | `docs/walkthrough-90s.md`, `docs/demo/operator/` |
| V2 | Independent re-audit of the fixes | see `docs/verification-reaudit.md` | - |
