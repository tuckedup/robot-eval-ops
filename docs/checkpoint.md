# Checkpoint status — 2026-10-20

The base implementation commit is `cb84c2ce854bfd9b5d27f03d1780303d24161c3a`. It contains the implemented
offline evaluation workflow: persisted SQLite sessions and trial lifecycle, mock and PyBullet Panda adapters,
recording/QA/quarantine, local artifact packaging and SHA-256 verification, metrics and reports, plus a guarded
SO-101/LeRobot pathway.  The hardware path remains software-gated and has not operated a robot.

## New verification at this checkpoint

All commands below used Python 3.11.16 from `D:\robot-eval-ops\.venv\Scripts\python.exe`, with `PYTHONPATH` set
to this checkout's `src` directory and `PYTHONDONTWRITEBYTECODE=1`.  An import assertion confirmed that
`robotevalops.__file__` resolved under this checkout, not under `D:\robot-eval-ops`.

- `python -m pytest tests\core -q` with `TEMP` and `TMP` redirected inside this checkpoint: **204 passed in
  58.49s**.
- `python -m pytest -m physics -q` with the same isolated temporary directory: **43 passed, 1 skipped, 652
  deselected in 142.96s**.  The skip is `tests/verification/test_sim_success_audit.py:206`, because
  `data/demo_sim` is not present.
- `uv build --wheel --out-dir .checkpoint-dist`: built
  `robotevalops-0.1.0-py3-none-any.whl`.  The build needed the lightweight Hatchling backend fetched by `uv`; no
  optional LeRobot stack was installed.
- The wheel was installed non-editably into a fresh local virtual environment.  From an unrelated directory, an
  import assertion resolved `robotevalops` from that environment's `site-packages`; `robotevalops --help` and
  `robotevalops demo run --skip-faults` both exited 0.  The demo used the **mock fixture**, explicitly labelled
  not evidence of robotics performance.  Its dependencies were made available read-only from the existing
  environment; this checks wheel contents and the entry point, not a clean dependency-resolution install.

No hardware, real AWS, paid service, or real LeRobot command was run.

## Existing evidence, not rerun here

`docs/verification-run.json` records successful lint, type, test, and physics runs for parent commit
`06ca1fe6e6a177c2f47ccf2413bb33e9c86e8e67`.  It is useful historical evidence only and is **not** verification
of this checkpoint's head.  Likewise, the tracked mock, simulation, fault-injection, stress-study, and report
artifacts document prior runs; their provenance labels remain controlling.  In particular, the 100-trial Panda
result is simulation with scripted controllers, and mock artifacts are fixtures, not robot-performance evidence.

## Content and publication review

A tracked-file scan found no common long-lived credential formats or tracked private-key/certificate-style
filenames. A candidate from a case-insensitive AWS-key-pattern scan at
`docs/demo/mock/report.html:51` was reviewed: it is mixed-case content inside an
embedded base64 image, not the uppercase AWS access-key-ID format. No credential
value is reproduced here. The more general credential-keyword matches are implementation references in
`src/robotevalops/adapters/lerobot_wrapper.py:59`,
`src/robotevalops/adapters/lerobot_wrapper.py:663`,
`src/robotevalops/storage/s3.py:246`,
`src/robotevalops/storage/s3.py:249`, and
`src/robotevalops/storage/s3.py:263`.

There is currently no `LICENSE` file.  Selecting an open-source license is an owner decision and remains a
publication limitation.

## Remaining release work

- Run the full offline suite, lint, and type checks on this exact head in a writable CI/clean environment; this
  checkpoint reran the core and physics suites only.
- Independently install the wheel with dependency resolution in a fresh environment (the local wheel demo used
  read-only existing dependencies).
- Exercise Docker, real AWS, real LeRobot dataset import/video scoring, and physical SO-101 preflight/operation
  only with the required hardware, credentials, and operator approval.  None is implied by the checks above.
- Choose a license and complete normal repository metadata/release review before publication.
