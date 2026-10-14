# SO-101 hardware setup and the simulation backends

> **Nothing in this repository has been verified on real hardware.** No SO-101, camera, motor or
> serial port was connected when this was written. The LeRobot wrapper, the SO-101 adapter and the
> commands below were exercised only with FAKE executables, fake port listers and fake camera
> probes (see `tests/robotics/`). The only things run against real software were the PyBullet
> Panda simulation and read-only discovery of the installed `lerobot` package.

## 1. Tested software versions (what was actually seen)

| Item | Observed in this environment |
|---|---|
| Python | 3.11 (project venv `.venv`) |
| lerobot | **0.4.4** (`importlib.metadata`), installed in `.venv`; not pinned in `pyproject.toml` |
| pybullet | 3.2.7 (bundled `franka_panda/panda.urdf`) |
| torch | 2.10.0 |
| pyserial | 3.5 |

Verified by inspecting the installed lerobot 0.4.4 (`robotevalops robot lerobot-info`):

* Console scripts present: `lerobot-calibrate`, `lerobot-dataset-viz`, `lerobot-edit-dataset`,
  `lerobot-eval`, `lerobot-find-cameras`, `lerobot-find-joint-limits`, `lerobot-find-port`,
  `lerobot-imgtransform-viz`, `lerobot-info`, `lerobot-record`, `lerobot-replay`,
  `lerobot-setup-can`, `lerobot-setup-motors`, `lerobot-teleoperate`, `lerobot-train`,
  `lerobot-train-tokenizer`.
* **There is no `lerobot-rollout` script in 0.4.4**, and no `lerobot.scripts.lerobot_rollout`
  module. Current online docs may describe newer tooling; this repository targets what is installed.
  Supervised learned-policy rollout is therefore built as `lerobot-record ... --policy.path=<ckpt>`
  (`lerobot_record.py` defines a `policy` option). The `lerobot-rollout` flags were not verified.
* SO-101 types are registered as `so101_follower` (module `lerobot.robots.so_follower`) and
  `so101_leader` (module `lerobot.teleoperators.so_leader`). The older module names
  `lerobot.robots.so101_follower` / `lerobot.teleoperators.so101_leader` do **not** exist in 0.4.4.
* Joint calibration files are `<id>.json` under
  `$HF_LEROBOT_CALIBRATION` (default `~/.cache/huggingface/lerobot/calibration`) in
  `robots/so_follower/` and `teleoperators/so_leader/` (the class `name` attributes in 0.4.4).
  The wrapper also checks the `so101_*` directory names for other versions.

## 2. Authoritative sources

* SO-101 assembly, motor setup, calibration, teleoperation: <https://huggingface.co/docs/lerobot/so101>
* Imitation learning on real robots (record, train, evaluate): <https://huggingface.co/docs/lerobot/il_robots>
* Source code and issues: <https://github.com/huggingface/lerobot>

These pages are authoritative; when they disagree with this file, follow them and check your
installed version with `robotevalops robot lerobot-info`.

## 3. Assembly overview (operator task)

Follow the SO-101 guide: 3D-print or purchase the parts, set motor IDs/baudrate on each Feetech
servo with `lerobot-setup-motors` (one at a time, as instructed), assemble the follower and the
leader arm, wire the controller boards, and plug each into USB. `lerobot-find-port` identifies the
serial port of each board. **This repository never runs setup-motors, flashing or calibration.**

## 4. Joint calibration vs camera calibration (two different things)

* **Joint calibration** records each motor's position range and zero offset so that leader and
  follower agree. It is made by an operator running `lerobot-calibrate` (the arm is moved by hand
  through its ranges) and saved as `<id>.json`. `lerobot-teleoperate` and `lerobot-record`
  **auto-start calibration if the file is missing**, which moves/relaxes motors. The wrapper
  therefore refuses to launch unless the follower and leader calibration files already exist.
* **Camera calibration** (intrinsics: focal length/distortion; extrinsics: camera pose relative to
  the robot base/table) is a separate vision concern. LeRobot does not use it. If you have it,
  keep your own record and reference it in the config key `camera_calibration_ref` (informational).

## 5. Configuration

Copy `src/robotevalops/configs/hardware/so101.example.yaml` to `src/robotevalops/configs/hardware/so101.yaml` and edit ids, ports,
cameras and task. All strings are validated with strict patterns (ids `[A-Za-z0-9_-]{1,64}`, ports
`COMn` or `/dev/...` without spaces/shell characters, repo ids `user/name`). Commands are
executed as **argument lists with `shell=False`**; no operator string is placed in a shell line.

Cameras: find OpenCV indices with `lerobot-find-cameras opencv`; the config becomes
`--robot.cameras="{ front: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30} }"`.
The preflight opens each configured camera device briefly to confirm it can be opened.

## 6. Commands (all via `robotevalops robot ...`)

```
robotevalops robot adapters                      # backends and availability
robotevalops robot lerobot-info                  # installed version, entry points, source URLs
robotevalops robot hardware-check --config src/robotevalops/configs/hardware/so101.yaml   # NON-MOVING preflight
robotevalops robot teleop   --config ... --dry-run                       # prints exact argv
robotevalops robot record   --config ... --dry-run
robotevalops robot rollout  --config ... --policy-path <ckpt> --dry-run
robotevalops robot import-dataset --path <lerobot dataset dir>           # read-only + episode split
```

Library callers (e.g. a runner) can call `SO101HardwareAdapter.check_motion_allowed()` (non-moving)
before starting a trial; it raises `HardwareRefusedError` unless hardware mode, a acknowledgement
bound to the adapter's session id (an unset session id never matches) and a passing preflight on
that instance all hold.

`teleop`, `record` and `rollout` refuse (exit code 2) unless **all** of these hold:
`--hardware-mode`, `--ack-operator NAME`, a passing preflight (config valid, lerobot executables
and modules found, both serial ports present, both joint-calibration files present, cameras
openable). `--dry-run` never executes anything; it prints the argument list and whether the run
would be refused. `calibrate` and `replay` command builders exist in the library as dry-run-only and
are not exposed by the CLI.

The preflight is non-moving: it enumerates serial ports (pyserial) without opening them, checks
files, and briefly opens camera devices.

### Teleoperation

`lerobot-teleoperate` moves the follower from the leader arm. The operator keeps the follower's
workspace clear, stays within reach of the power switch, and starts with the leader slowly.

### Recording

`lerobot-record` writes a LeRobot dataset (`--dataset.push_to_hub=false` is always passed). The
adapter's `run_episode` records one episode into `<out_dir>/lerobot_dataset`, copies the first
video it finds to `video.mp4`, returns `task_success=None` (an operator must score from the video)
and intervention `unknown`. If the dataset's `data/**/*.parquet` is readable (pandas + pyarrow)
and has `timestamp`, `observation.state` and `action` columns, `trace.jsonl` is written with those
values copied exactly (NaNs preserved; nothing repaired) and completeness is measured as frames
decodable from `video.mp4` divided by dataset rows (0 if the video cannot be decoded, e.g. a codec
OpenCV lacks). Otherwise the trace is left absent and `evidence.trace_absent_reason` says why. This
conversion was tested only on a SYNTHETIC LeRobot-style fixture written by a fake executable; it
has never seen a real LeRobot dataset.

### Supervised rollout

For a trained policy, `rollout` builds `lerobot-record --policy.path=<ckpt>` (controller type
`learned`). A person must supervise with the e-stop within reach. No trained checkpoint exists in
this repository.

## 7. What the operator must do (never automated here)

Assemble and wire the arms; run `lerobot-setup-motors`; run `lerobot-calibrate` for follower and
leader; choose ports/cameras; clear and reset the workspace between trials; score each trial from
its video; stay present during any motion; own the physical emergency stop.

## 8. Safety

* The **emergency stop is a hardware/facility procedure** (cut motor power at a switch within
  reach). `request_stop()` and `--timeout` are software controls that kill the lerobot subprocess;
  they have no latency guarantee and are **not** an emergency stop.
* Hardware motion needs explicit hardware mode, a per-session operator acknowledgement and a
  passing preflight; nothing moves in install or CI.
* A scripted controller never runs on the SO-101 adapter. No LLM output drives robot motion.

## 9. Simulation backend (PyBullet Panda; not the SO-101)

`pybullet_panda` runs a **Franka Panda** in simulation (DIRECT mode, 240 Hz physics, 20 Hz control,
10 Hz trace/video). Geometry: table top z=0; 4 cm block (50 g) nominally at (0.50, -0.15); target
region a 12 cm square centred at (0.50, 0.20) (half side 0.06 m, so 4 cm slack per axis for the
axis-aligned block). This is PICK-and-place, so success is read from physics and requires all of: a
grasp (both fingers in contact with the block for >= 5 control steps), a lift (block centre rose
>= 0.03 m above its resting height at some point), then placement with all 8 block corners STRICTLY
inside the square (a corner on the boundary does not count; no tolerance), the gripper released
(opening >= 0.06 m and no Panda-block contact points), continuously for 2.0 s within a 30 s attempt.
If the placement dwell is met without a grasp+lift (e.g. the block was pushed), the episode runs to
the timeout and is a failure; `evidence.failed_criteria` lists which criterion failed and
`evidence.grasped`, `lift_m`, `both_finger_contact_steps` record the measurements.
`run_episode` refuses `timeout_s <= 0` or `dwell_required_s <= 0`. The block is created once and never repositioned. Frames are "rendered simulator frames"
(TinyRenderer 320x240), not camera data. Visual conditions (lighting, background, occlusion) change
only the rendered image; the scripted controllers read simulator state, so they are not expected to
react to them and the results say nothing about learned-policy robustness.

### Simulation results (local run)

Re-measured AFTER the grasp+lift+strict-inclusion criteria were added (Windows, pybullet 3.2.7,
rendering + recording ON, seeds 100-104 per cell,
5 trials per cell, 30 s attempt, 2.0 s dwell). Successes are physics-derived (see above); every run
recorded video + trace with completeness 1.0; lift of the block was >= 0.19 m in all 50 runs;
episodes lasted 9.6-14.0 s of simulated time.

| Controller (v1) | nominal | object_position | lighting | background | occlusion |
|---|---|---|---|---|---|
| scripted_baseline_a | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 |
| scripted_baseline_b | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 |

Caveats: n=5 per cell is far too small for any rate or significance claim (Wilson 95% lower bound
for 5/5 is about 57%); these are smoke-level counts. Because the controllers read state, the 5/5 under
lighting/background/occlusion is the expected result and is **not** evidence about visual
robustness. During tuning (no rendering) both configs also went 10/10 on nominal and object_position
for seeds 0-9 with slightly different parameters than the final B config; only the table above is
for the shipped configs. Reproduce: `robotevalops robot sim-smoke --trials 3 --controller
scripted_baseline_a --condition nominal`.

## 10. Optional: ACT training workflow — **UNEXECUTED**

Not run here: no compatible dataset exists and training was out of scope. For reference only
(check flags against the il_robots page and your installed version before use):

```
lerobot-train --policy.type=act --dataset.repo_id=<user>/<dataset> \
  --output_dir=outputs/train/act_so101 --job_name=act_so101 \
  --policy.device=cuda --policy.push_to_hub=false --wandb.enable=false
```

Split data by **whole episodes** (`robotevalops robot import-dataset --path ...` prints a
deterministic episode-level split); never put adjacent frames of one episode into both train and
evaluation. A trained checkpoint must be registered as a `learned` controller with its SHA-256.
