"""PyBullet Franka Panda pick-and-place simulation adapter (provenance SIMULATION).

This is a PANDA arm in simulation. It is not an SO-101 and says nothing about hardware.

Scene geometry (world frame, metres, z up; all documented constants below):
  * table top at z = 0, a fixed box covering x in [-0.20, 0.90], y in [-0.50, 0.50]
  * Panda base at the origin (bundled ``franka_panda/panda.urdf``, fixed base)
  * block: 4 cm cube (half extent 0.02), mass 0.05 kg, nominal start (0.50, -0.15), yaw 0
  * target region: axis-aligned SQUARE on the table, centre (0.50, 0.20), half side 0.06 m
    (12 cm x 12 cm). Drawn as a visual-only green marker (no collision, no effect on physics).
    The block footprint is 4 cm, so every footprint corner must lie within +/-0.06 m of the centre:
    a placement tolerance of 4 cm per axis for an axis-aligned block.
Timing: physics 240 Hz fixed step; control 20 Hz (12 physics substeps per control step); trace rows and
rendered frames are recorded at 10 Hz (every 2nd control step; TinyRenderer cost dominates).
Success (all derived from simulator state, never a flag):
  every footprint corner of the block inside the target square AND gripper released
  (finger opening >= 0.06 m AND no contact points between any Panda link and the block) AND this
  holds continuously for ``dwell_required_s`` (default 2.0 s of simulated time) within the attempt
  timeout (30 s). The block is created once at reset and is NEVER repositioned afterwards.
Rendered frames: TinyRenderer 320x240 "rendered simulator frames" (not camera observations).
Visual conditions (lighting/background/occlusion) change only the rendered image.
"""

from __future__ import annotations

import contextlib
import math
from pathlib import Path
from typing import Any

import numpy as np

from robotevalops.adapters.base import (
    Action,
    Controller,
    EpisodeResult,
    Observation,
    PreflightCheck,
    PreflightResult,
    RobotAdapter,
    StepResult,
)
from robotevalops.controllers.base import StopRequestedError, condition_param, seeded_rng
from robotevalops.errors import CapabilityUnavailableError, RobotEvalOpsError
from robotevalops.recording.writers import TrialRecorder
from robotevalops.schemas import (
    ConditionSpec,
    Provenance,
    RecordingSummary,
    TerminationReason,
)

SIM_HZ = 240
CONTROL_HZ = 20
REC_EVERY = (
    2  # trace rows + rendered frames are recorded every 2nd control step (10 Hz): rendering dominates cost
)
REC_HZ = CONTROL_HZ / REC_EVERY
SUBSTEPS = SIM_HZ // CONTROL_HZ
FRAME_W, FRAME_H = 320, 240

BLOCK_HALF = 0.02
BLOCK_MASS = 0.05
BLOCK_NOMINAL_XY = (0.50, -0.15)
TARGET_CENTER = (0.50, 0.20)
TARGET_HALF = 0.06
OPEN_THRESHOLD_M = 0.06  # sum of both finger positions
EE_LINK = 11  # panda_grasptarget
ARM_JOINTS = list(range(7))
FINGER_JOINTS = [9, 10]
HOME_JOINTS = [0.0, -0.4, 0.0, -2.2, 0.0, 1.8, 0.785]

STATE_NAMES = (
    [f"joint_pos_{i}" for i in range(7)]
    + ["gripper_width"]
    + ["ee_x", "ee_y", "ee_z"]
    + ["block_x", "block_y", "block_z"]
    + ["block_qx", "block_qy", "block_qz", "block_qw"]
)
ACTION_NAMES = [f"joint_target_{i}" for i in range(7)] + ["finger_target_m", "grip_force_n"]

_NOMINAL_LIGHT_DIR = (0.5, -0.4, 1.0)
_NOMINAL_TABLE_RGB = (0.76, 0.60, 0.42)
_NOMINAL_FLOOR_RGB = (0.55, 0.55, 0.55)


def _import_pybullet() -> Any:
    try:
        import pybullet
    except ImportError as e:  # pragma: no cover - exercised via registry test with monkeypatch
        raise CapabilityUnavailableError(
            "pybullet is not installed; install the simulation extra (uv sync --extra sim) to use "
            "the pybullet_panda backend"
        ) from e
    return pybullet


def _panda_urdf() -> str:
    import pybullet_data

    path = Path(pybullet_data.getDataPath()) / "franka_panda" / "panda.urdf"
    if not path.exists():
        raise CapabilityUnavailableError(f"bundled Panda URDF not found at {path}")
    return str(path)


def panda_urdf_path() -> str:
    """Path of the bundled Panda URDF (also used by the controller's private IK solver)."""
    _import_pybullet()
    return _panda_urdf()


def _rot(quat: np.ndarray) -> np.ndarray:
    x, y, z, w = (float(v) for v in quat)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def footprint_fraction_in_square(
    pos: np.ndarray, quat: np.ndarray, center: tuple[float, float], half: float, n: int = 21
) -> float:
    """Fraction of the block's bottom-face area lying inside the target square (grid sampling)."""
    g = np.linspace(-BLOCK_HALF, BLOCK_HALF, n)
    gx, gy = np.meshgrid(g, g)
    local = np.stack([gx.ravel(), gy.ravel(), np.full(gx.size, -BLOCK_HALF)], axis=1)
    world = local @ _rot(quat).T + pos
    inside = (np.abs(world[:, 0] - center[0]) <= half) & (np.abs(world[:, 1] - center[1]) <= half)
    return float(inside.mean())


def corners_inside_square(
    pos: np.ndarray, quat: np.ndarray, center: tuple[float, float], half: float
) -> bool:
    """True iff all 4 bottom-face corners of the cube are inside the square region."""
    corners = np.array([[sx * BLOCK_HALF, sy * BLOCK_HALF, -BLOCK_HALF] for sx in (-1, 1) for sy in (-1, 1)])
    world = corners @ _rot(quat).T + pos
    return bool(
        np.all(np.abs(world[:, 0] - center[0]) <= half) and np.all(np.abs(world[:, 1] - center[1]) <= half)
    )


class PyBulletPandaAdapter(RobotAdapter):
    provenance = Provenance.SIMULATION
    name = "pybullet_panda"

    def __init__(self, render: bool = True) -> None:
        self.p = _import_pybullet()
        self.render = render
        self._cid: int | None = None
        self._stop = False
        self._condition: ConditionSpec | None = None
        self._seed = 0
        self._recorder: TrialRecorder | None = None
        self._rec_steps = 0
        self._reset_state()

    # ------------------------------------------------------------------ state
    def _reset_state(self) -> None:
        self._panda = -1
        self._block = -1
        self._table = -1
        self._floor = -1
        self._t = 0.0
        self._steps = 0
        self._dwell = 0.0
        self._success = False
        self._target = [0.0] * 9
        self._arm_forces: list[float] = []
        self._finger_target = 0.04
        self._finger_force = 20.0
        self._block_start = np.zeros(3)
        self._applied: dict[str, Any] = {}
        self._light: dict[str, Any] = {}
        self._occlusion: tuple[int, int, int, int] | None = None
        self._dwell_required = 2.0
        self._ev: dict[str, Any] = {}

    def _connect(self) -> int:
        if self._cid is None:
            self._cid = self.p.connect(self.p.DIRECT)
        return self._cid

    # -------------------------------------------------------------- preflight
    def preflight(self) -> PreflightResult:
        checks: list[PreflightCheck] = []
        try:
            _import_pybullet()
            checks.append(PreflightCheck("pybullet_import", True, f"pybullet {self.p.getAPIVersion()}"))
        except CapabilityUnavailableError as e:
            return PreflightResult([PreflightCheck("pybullet_import", False, str(e))])
        try:
            urdf = _panda_urdf()
            checks.append(PreflightCheck("panda_urdf", True, urdf))
        except CapabilityUnavailableError as e:
            checks.append(PreflightCheck("panda_urdf", False, str(e)))
        try:
            cid = self.p.connect(self.p.DIRECT)
            try:
                view = self.p.computeViewMatrix([1, 0, 1], [0, 0, 0], [0, 0, 1])
                proj = self.p.computeProjectionMatrixFOV(60, FRAME_W / FRAME_H, 0.05, 3.0)
                img = self.p.getCameraImage(
                    FRAME_W, FRAME_H, view, proj, renderer=self.p.ER_TINY_RENDERER, physicsClientId=cid
                )
                ok = int(img[0]) == FRAME_W and int(img[1]) == FRAME_H
                checks.append(
                    PreflightCheck("render_tinyrenderer", ok, f"{FRAME_W}x{FRAME_H} frame rendered")
                )
            finally:
                self.p.disconnect(cid)
        except Exception as e:  # noqa: BLE001
            checks.append(PreflightCheck("render_tinyrenderer", False, f"render failed: {e}"))
        try:
            import imageio_ffmpeg

            imageio_ffmpeg.get_ffmpeg_exe()
            checks.append(PreflightCheck("video_encoder", True, "imageio-ffmpeg available"))
        except Exception as e:  # noqa: BLE001
            checks.append(PreflightCheck("video_encoder", False, f"imageio-ffmpeg unavailable: {e}"))
        return PreflightResult(checks)

    # ------------------------------------------------------------------ reset
    def reset(self, condition: ConditionSpec, seed: int) -> Observation:
        if self._stop:
            raise StopRequestedError("pybullet adapter: stop was requested; create a new adapter")
        p = self.p
        cid = self._connect()
        p.resetSimulation(physicsClientId=cid)
        self._reset_state()
        self._condition, self._seed = condition, int(seed)
        p.setGravity(0, 0, -9.81, physicsClientId=cid)
        p.setPhysicsEngineParameter(
            fixedTimeStep=1.0 / SIM_HZ,
            numSolverIterations=100,
            deterministicOverlappingPairs=1,
            physicsClientId=cid,
        )
        p.setTimeStep(1.0 / SIM_HZ, physicsClientId=cid)

        # --- table + floor
        tcol = p.createCollisionShape(p.GEOM_BOX, halfExtents=[0.55, 0.5, 0.02], physicsClientId=cid)
        tvis = p.createVisualShape(
            p.GEOM_BOX, halfExtents=[0.55, 0.5, 0.02], rgbaColor=[*_NOMINAL_TABLE_RGB, 1], physicsClientId=cid
        )
        self._table = p.createMultiBody(0, tcol, tvis, [0.35, 0.0, -0.02], physicsClientId=cid)
        fcol = p.createCollisionShape(p.GEOM_BOX, halfExtents=[3, 3, 0.02], physicsClientId=cid)
        fvis = p.createVisualShape(
            p.GEOM_BOX, halfExtents=[3, 3, 0.02], rgbaColor=[*_NOMINAL_FLOOR_RGB, 1], physicsClientId=cid
        )
        self._floor = p.createMultiBody(0, fcol, fvis, [0.35, 0.0, -0.52], physicsClientId=cid)
        p.changeDynamics(self._table, -1, lateralFriction=0.8, physicsClientId=cid)
        # --- target marker (visual only)
        mvis = p.createVisualShape(
            p.GEOM_BOX,
            halfExtents=[TARGET_HALF, TARGET_HALF, 0.0005],
            rgbaColor=[0.1, 0.7, 0.2, 1],
            physicsClientId=cid,
        )
        p.createMultiBody(0, -1, mvis, [TARGET_CENTER[0], TARGET_CENTER[1], 0.0006], physicsClientId=cid)

        # --- panda
        self._panda = p.loadURDF(_panda_urdf(), [0, 0, 0], useFixedBase=True, physicsClientId=cid)
        for j, q in zip(ARM_JOINTS, HOME_JOINTS, strict=True):
            p.resetJointState(self._panda, j, q, physicsClientId=cid)
        for j in FINGER_JOINTS:
            p.resetJointState(self._panda, j, 0.04, physicsClientId=cid)
            p.changeDynamics(self._panda, j, lateralFriction=1.5, spinningFriction=0.01, physicsClientId=cid)
        self._arm_forces = [
            float(p.getJointInfo(self._panda, j, physicsClientId=cid)[10]) for j in ARM_JOINTS
        ]
        self._target = [*HOME_JOINTS, 0.04, 20.0]

        # --- block (state-affecting condition: seeded bounded offset)
        sx, sy = BLOCK_NOMINAL_XY
        self._applied = {"condition_kind": condition.kind, "condition_name": condition.name}
        if condition.kind == "object_position":
            m = condition_param(condition, "max_offset_m", 0.04)
            m = min(abs(m), 0.06)  # hard bound regardless of config
            off = seeded_rng(seed, "object_position").uniform(-m, m, size=2)
            sx, sy = sx + float(off[0]), sy + float(off[1])
            self._applied.update({"block_offset_m": [float(off[0]), float(off[1])], "max_offset_m": m})
        bcol = p.createCollisionShape(p.GEOM_BOX, halfExtents=[BLOCK_HALF] * 3, physicsClientId=cid)
        bvis = p.createVisualShape(
            p.GEOM_BOX, halfExtents=[BLOCK_HALF] * 3, rgbaColor=[0.85, 0.1, 0.1, 1], physicsClientId=cid
        )
        self._block = p.createMultiBody(
            BLOCK_MASS, bcol, bvis, [sx, sy, BLOCK_HALF + 0.0002], physicsClientId=cid
        )
        p.changeDynamics(self._block, -1, lateralFriction=1.0, physicsClientId=cid)

        # --- visual-only conditions (separate RNG stream; never touches physics)
        self._light = {"dir": _NOMINAL_LIGHT_DIR, "scale": 1.0}
        self._occlusion = None
        vrng = seeded_rng(seed, "visual", condition.kind)
        if condition.kind == "lighting":
            amax = math.radians(condition_param(condition, "azimuth_deg_max", 80.0))
            az = float(vrng.uniform(-amax, amax))
            lo, hi = (
                condition_param(condition, "intensity_min", 0.3),
                condition_param(condition, "intensity_max", 1.0),
            )
            scale = float(vrng.uniform(lo, hi))
            dx, dy, dz = _NOMINAL_LIGHT_DIR
            ldir = (dx * math.cos(az) - dy * math.sin(az), dx * math.sin(az) + dy * math.cos(az), dz)
            self._light = {"dir": ldir, "scale": scale}
            self._applied.update({"light_azimuth_rad": az, "light_intensity_scale": scale})
        elif condition.kind == "background":
            d = condition_param(condition, "color_delta", 0.35)
            for body, base, key in (
                (self._table, _NOMINAL_TABLE_RGB, "table_rgb"),
                (self._floor, _NOMINAL_FLOOR_RGB, "floor_rgb"),
            ):
                rgb = np.clip(np.array(base) + vrng.uniform(-d, d, size=3), 0.0, 1.0)
                p.changeVisualShape(body, -1, rgbaColor=[*[float(c) for c in rgb], 1.0], physicsClientId=cid)
                self._applied[key] = [float(c) for c in rgb]
        elif condition.kind == "occlusion":
            lo, hi = (
                condition_param(condition, "patch_frac_min", 0.10),
                condition_param(condition, "patch_frac_max", 0.25),
            )
            f = float(vrng.uniform(lo, hi))
            pw, ph = int(f * FRAME_W), int(f * FRAME_H)
            x0 = int(vrng.integers(0, FRAME_W - pw + 1))
            y0 = int(vrng.integers(0, FRAME_H - ph + 1))
            self._occlusion = (x0, y0, pw, ph)
            self._applied.update({"occlusion_patch_xywh_px": [x0, y0, pw, ph], "occlusion_frac": f})

        # --- settle under gravity with the arm holding the home pose (0.5 s); no repositioning
        self._apply_motors()
        for _ in range(SIM_HZ // 2):
            p.stepSimulation(physicsClientId=cid)
        self._block_start = np.array(p.getBasePositionAndOrientation(self._block, physicsClientId=cid)[0])
        self._ev = {
            "gripper_contact_steps": 0,
            "both_finger_contact_steps": 0,
            "max_block_z_m": float(self._block_start[2]),
            "max_contact_normal_force_n": 0.0,
        }
        return self.observe()

    # ----------------------------------------------------------------- helpers
    def _apply_motors(self) -> None:
        p, cid = self.p, self._cid
        p.setJointMotorControlArray(
            self._panda,
            ARM_JOINTS,
            p.POSITION_CONTROL,
            targetPositions=self._target[:7],
            forces=self._arm_forces,
            physicsClientId=cid,
        )
        p.setJointMotorControlArray(
            self._panda,
            FINGER_JOINTS,
            p.POSITION_CONTROL,
            targetPositions=[self._finger_target] * 2,
            forces=[self._finger_force] * 2,
            physicsClientId=cid,
        )

    def _block_pose(self) -> tuple[np.ndarray, np.ndarray]:
        pos, quat = self.p.getBasePositionAndOrientation(self._block, physicsClientId=self._cid)
        return np.array(pos), np.array(quat)

    def _contacts(self) -> tuple[int, int, float]:
        """(# block-Panda contact points, # distinct finger links in contact, sum normal force)."""
        pts = self.p.getContactPoints(bodyA=self._block, bodyB=self._panda, physicsClientId=self._cid)
        fingers = {c[4] for c in pts if c[4] in FINGER_JOINTS}
        return len(pts), len(fingers), float(sum(c[9] for c in pts))

    def _finger_width(self) -> float:
        st = self.p.getJointStates(self._panda, FINGER_JOINTS, physicsClientId=self._cid)
        return float(st[0][0] + st[1][0])

    def _render_frame(self) -> np.ndarray:
        p, cid = self.p, self._cid
        view = p.computeViewMatrix([1.05, 0.0, 0.65], [0.45, 0.02, 0.02], [0, 0, 1])
        proj = p.computeProjectionMatrixFOV(60, FRAME_W / FRAME_H, 0.05, 4.0)
        s = float(self._light["scale"])
        out = p.getCameraImage(
            FRAME_W,
            FRAME_H,
            view,
            proj,
            lightDirection=list(self._light["dir"]),
            lightColor=[s, s, s],
            lightDistance=2.0,
            shadow=0,
            lightAmbientCoeff=0.6 * s,
            lightDiffuseCoeff=0.4 * s,
            lightSpecularCoeff=0.3 * s,
            renderer=p.ER_TINY_RENDERER,
            physicsClientId=cid,
        )
        rgba = np.reshape(np.asarray(out[2], dtype=np.uint8), (FRAME_H, FRAME_W, 4))
        img = np.ascontiguousarray(rgba[..., :3])
        if self._occlusion is not None:
            x0, y0, pw, ph = self._occlusion
            img[y0 : y0 + ph, x0 : x0 + pw, :] = 128
        return img

    def _vectors(self) -> dict[str, list[float]]:
        p, cid = self.p, self._cid
        js = p.getJointStates(self._panda, ARM_JOINTS, physicsClientId=cid)
        ls = p.getLinkState(self._panda, EE_LINK, computeForwardKinematics=1, physicsClientId=cid)
        bpos, bquat = self._block_pose()
        return {
            "joint_pos": [float(s[0]) for s in js],
            "joint_vel": [float(s[1]) for s in js],
            "gripper_width": [self._finger_width()],
            "ee_pos_world": [float(v) for v in ls[4]],
            "ee_quat_world": [float(v) for v in ls[5]],
            "block_pos_world": [float(v) for v in bpos],
            "block_quat_world": [float(v) for v in bquat],
            "target_center_world": [TARGET_CENTER[0], TARGET_CENTER[1], 0.0],
            "target_half_size_m": [TARGET_HALF],
        }

    def state_vector(self, st: dict[str, list[float]]) -> list[float]:
        return (
            st["joint_pos"]
            + st["gripper_width"]
            + st["ee_pos_world"]
            + st["block_pos_world"]
            + st["block_quat_world"]
        )

    def observe(self, render: bool = True) -> Observation:
        if self._panda < 0:
            raise RobotEvalOpsError("observe() requires reset() first")
        img = self._render_frame() if (self.render and render) else None
        return Observation(t=self._t, state=self._vectors(), image=img)

    # -------------------------------------------------------------------- act
    def act(self, action: Action) -> None:
        if self._stop:
            raise StopRequestedError("pybullet adapter: act() after request_stop() is refused")
        v = list(action.values)
        if len(v) != 9 or not all(math.isfinite(x) for x in v):
            raise ValueError(f"action must be 9 finite values {ACTION_NAMES}; got {v}")
        lows, highs = [], []
        for j in ARM_JOINTS:
            info = self.p.getJointInfo(self._panda, j, physicsClientId=self._cid)
            lows.append(info[8])
            highs.append(info[9])
        q = [min(max(x, lo), hi) for x, lo, hi in zip(v[:7], lows, highs, strict=True)]
        self._target[:7] = q
        self._finger_target = min(max(v[7], 0.0), 0.04)
        self._finger_force = min(max(v[8], 0.0), 40.0)

    def _update_task(self) -> None:
        pos, quat = self._block_pose()
        n_pts, n_fingers, fsum = self._contacts()
        inside = corners_inside_square(pos, quat, TARGET_CENTER, TARGET_HALF)
        released = self._finger_width() >= OPEN_THRESHOLD_M and n_pts == 0
        ev = self._ev
        ev["max_block_z_m"] = max(ev["max_block_z_m"], float(pos[2]))
        ev["max_contact_normal_force_n"] = max(ev["max_contact_normal_force_n"], fsum)
        if n_pts:
            ev["gripper_contact_steps"] += 1
        if n_fingers >= 2:
            ev["both_finger_contact_steps"] += 1
        if inside and released:
            self._dwell += 1.0 / CONTROL_HZ
        else:
            self._dwell = 0.0
        ev["dwell_s_max"] = max(ev.get("dwell_s_max", 0.0), self._dwell)
        self._success = self._dwell + 1e-9 >= self._dwell_required

    def step(self) -> StepResult:
        if self._stop:
            raise StopRequestedError("pybullet adapter: step() after request_stop() is refused")
        self._apply_motors()
        for _ in range(SUBSTEPS):
            self.p.stepSimulation(physicsClientId=self._cid)
        self._t += 1.0 / CONTROL_HZ
        self._steps += 1
        self._update_task()
        return StepResult(
            self.observe(render=self._steps % REC_EVERY == 0),
            done=self._success,
            info={"dwell_s": self._dwell},
        )

    # ----------------------------------------------------------- stop/record
    def request_stop(self) -> None:
        self._stop = True

    @property
    def stop_requested(self) -> bool:
        return self._stop

    def start_recording(self, out_dir: Path) -> None:
        self._recorder = TrialRecorder(
            out_dir,
            REC_HZ,
            STATE_NAMES,
            ACTION_NAMES,
            Provenance.SIMULATION,
            frame_size=(FRAME_W, FRAME_H) if self.render else None,
            video_kind="rendered_simulator_frames",
        )
        self._rec_steps = 0

    def stop_recording(self) -> RecordingSummary:
        if self._recorder is None:
            raise RobotEvalOpsError("stop_recording() without start_recording()")
        rec, self._recorder = self._recorder, None
        return rec.close(expected_steps=self._rec_steps)

    def close(self) -> None:
        if self._recorder is not None:
            self._recorder.close()
            self._recorder = None
        if self._cid is not None:
            with contextlib.suppress(Exception):
                self.p.disconnect(self._cid)
            self._cid = None

    # ---------------------------------------------------------------- episode
    def _final_evidence(self) -> dict[str, Any]:
        pos, quat = self._block_pose()
        n_pts, n_fingers, _ = self._contacts()
        width = self._finger_width()
        lin = self.p.getBaseVelocity(self._block, physicsClientId=self._cid)[0]
        ev = self._ev
        return {
            "block_start_pos": [float(x) for x in self._block_start],
            "block_final_pos": [float(x) for x in pos],
            "block_final_quat": [float(x) for x in quat],
            "block_displacement_m": float(np.linalg.norm(pos[:2] - self._block_start[:2])),
            "block_final_speed_mps": float(np.linalg.norm(lin)),
            "in_target_fraction": footprint_fraction_in_square(pos, quat, TARGET_CENTER, TARGET_HALF),
            "all_corners_inside": corners_inside_square(pos, quat, TARGET_CENTER, TARGET_HALF),
            "released": bool(width >= OPEN_THRESHOLD_M and n_pts == 0),
            "gripper_width_m": width,
            "gripper_block_contact_points_final": n_pts,
            "dwell_s": self._dwell,
            "dwell_required_s": self._dwell_required,
            "dwell_s_max": ev.get("dwell_s_max", 0.0),
            "gripper_contact_steps": ev["gripper_contact_steps"],
            "both_finger_contact_steps": ev["both_finger_contact_steps"],
            "max_block_height_m": ev["max_block_z_m"],
            "lift_m": ev["max_block_z_m"] - float(self._block_start[2]),
            "max_contact_normal_force_n": ev["max_contact_normal_force_n"],
            "control_steps": self._steps,
            "sim_time_s": self._t,
            "target_center_xy": list(TARGET_CENTER),
            "target_half_size_m": TARGET_HALF,
            "applied_condition": self._applied,
            "frames": f"rendered simulator frames (TinyRenderer {FRAME_W}x{FRAME_H}); not camera data",
            "robot": "franka_panda (simulation only; not SO-101)",
            "sim_hz": SIM_HZ,
            "control_hz": CONTROL_HZ,
            "record_hz": REC_HZ,
        }

    def run_episode(
        self, controller: Controller, out_dir: Path, timeout_s: float, dwell_required_s: float
    ) -> EpisodeResult:
        if self._condition is None or self._panda < 0:
            raise RobotEvalOpsError("run_episode() requires reset() first")
        self._dwell_required = float(dwell_required_s)
        max_steps = int(math.ceil(timeout_s * CONTROL_HZ))
        try:
            self.start_recording(Path(out_dir))
        except Exception as e:  # noqa: BLE001
            return EpisodeResult(
                TerminationReason.RECORDING_FAILURE,
                0.0,
                None,
                self._final_evidence(),
                RecordingSummary(),
                error=f"could not start recording: {type(e).__name__}: {e}",
            )
        reason = TerminationReason.TIMEOUT
        error: str | None = None
        t_end = 0.0
        try:
            obs = self.observe()
            controller.reset(obs, self._seed)
            for _ in range(max_steps):
                if self._stop:
                    reason = TerminationReason.SOFTWARE_STOP_REQUEST
                    break
                action = controller.act(obs)
                assert self._recorder is not None
                if self._steps % REC_EVERY == 0:
                    self._recorder.add(obs.t, obs.image, self.state_vector(obs.state), list(action.values))
                    self._rec_steps += 1
                self.act(action)
                res = self.step()
                obs, t_end = res.observation, self._t
                if res.done:
                    reason = TerminationReason.SUCCESS_CRITERION_MET
                    break
        except StopRequestedError:
            reason = TerminationReason.SOFTWARE_STOP_REQUEST
        except Exception as e:  # noqa: BLE001 - simulator/controller errors become INFRA_FAILURE
            reason = TerminationReason.INFRA_FAILURE
            error = f"{type(e).__name__}: {e}"
        try:
            summary = self.stop_recording()
        except Exception as e:  # noqa: BLE001
            reason = TerminationReason.RECORDING_FAILURE
            error = (error + "; " if error else "") + f"recorder close failed: {type(e).__name__}: {e}"
            summary = RecordingSummary()
        ev = self._final_evidence()
        success: bool | None
        if reason == TerminationReason.SUCCESS_CRITERION_MET:
            success = True
        elif reason == TerminationReason.TIMEOUT:
            success = False
        else:
            success = None  # stopped/infra/recording failure: task not judged
        return EpisodeResult(reason, float(t_end or self._t), success, ev, summary, error=error)
