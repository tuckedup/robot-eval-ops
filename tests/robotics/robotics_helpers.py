"""Helpers for robotics tests. The "lerobot" executables used here are FAKE tiny Python scripts
(run via sys.executable); they never touch hardware and prove nothing about real LeRobot."""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

from robotevalops.adapters.lerobot_wrapper import LeRobotInfo, SO101Config

FAKE_SCRIPT = textwrap.dedent(
    """
    import json, sys, time
    from pathlib import Path

    mode, log = sys.argv[1], sys.argv[2]
    args = sys.argv[3:]
    Path(log).write_text(json.dumps(args), encoding="utf-8")
    if mode == "nonzero":
        sys.stderr.write("fake failure: motors not found\\n")
        sys.exit(3)
    if mode == "sleep":
        time.sleep(60)
    if mode in ("dataset", "dataset_no_video"):
        root = None
        for a in args:
            if a.startswith("--dataset.root="):
                root = Path(a.split("=", 1)[1])
        if root is not None:
            (root / "meta").mkdir(parents=True, exist_ok=True)
            (root / "meta" / "info.json").write_text(
                json.dumps({"total_episodes": 1, "fps": 30, "features": {}}), encoding="utf-8")
            if mode == "dataset":
                (root / "videos" / "chunk-000").mkdir(parents=True, exist_ok=True)
                (root / "videos" / "chunk-000" / "file-000.mp4").write_bytes(b"FAKE-VIDEO-BYTES")
    if mode == "dataset_parquet":
        # SYNTHETIC LeRobot-STYLE dataset (not recorded from any robot)
        import os, shutil
        import pandas as pd
        root = None
        for a in args:
            if a.startswith("--dataset.root="):
                root = Path(a.split("=", 1)[1])
        (root / "meta").mkdir(parents=True, exist_ok=True)
        (root / "meta" / "info.json").write_text(json.dumps({
            "total_episodes": 1, "fps": 10,
            "features": {"observation.state": {"names": ["j0", "j1"]}, "action": {"names": ["a0", "a1"]}},
        }), encoding="utf-8")
        (root / "data" / "chunk-000").mkdir(parents=True, exist_ok=True)
        pd.DataFrame({
            "timestamp": [0.0, 0.1, 0.2, 0.3],
            "episode_index": [0, 0, 0, 0],
            "observation.state": [[0.0, 1.0], [0.5, 1.5], [1.0, 2.0], [float("nan"), 2.5]],
            "action": [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6], [0.7, 0.8]],
        }).to_parquet(root / "data" / "chunk-000" / "file-000.parquet")
        if os.environ.get("FAKE_VIDEO"):
            (root / "videos" / "chunk-000").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(os.environ["FAKE_VIDEO"], root / "videos" / "chunk-000" / "file-000.mp4")
    print("fake lerobot ran")
    """
)


def write_fake(tmp_path: Path) -> Path:
    p = tmp_path / "fake_lerobot.py"
    p.write_text(FAKE_SCRIPT, encoding="utf-8")
    return p


def overrides(tmp_path: Path, mode: str = "ok", log_name: str = "argv.json") -> dict[str, list[str]]:
    script = write_fake(tmp_path)
    log = str(tmp_path / log_name)
    return {
        tool: [sys.executable, str(script), mode, log]
        for tool in ("lerobot-teleoperate", "lerobot-record", "lerobot-calibrate", "lerobot-replay")
    }


def read_argv(tmp_path: Path, log_name: str = "argv.json") -> list[str]:
    return json.loads((tmp_path / log_name).read_text(encoding="utf-8"))


def make_cfg(**kw: object) -> SO101Config:
    base: dict[str, object] = {
        "follower_id": "fol_1",
        "follower_port": "COM3",
        "leader_id": "lead_1",
        "leader_port": "COM4",
        "cameras": {"front": {"type": "opencv", "index_or_path": 0, "width": 640, "height": 480, "fps": 30}},
    }
    base.update(kw)
    return SO101Config.model_validate(base)


def make_calibration(root: Path, cfg: SO101Config) -> None:
    for sub, name, ident in (
        ("robots", "so_follower", cfg.follower_id),
        ("teleoperators", "so_leader", cfg.leader_id),
    ):
        d = root / sub / name
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{ident}.json").write_text("{}", encoding="utf-8")


def fake_info(ov: dict[str, list[str]]) -> LeRobotInfo:
    exes: dict[str, list[str] | None] = {k: list(v) for k, v in ov.items()}
    return LeRobotInfo(
        version="fake-0.0",
        executables=exes,
        has_so_follower=True,
        has_so_leader=True,
        has_rollout_tool=False,
        package_dir=None,
    )
