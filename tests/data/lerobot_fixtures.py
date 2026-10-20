"""Small synthetic LeRobot v3 datasets for offline adapter tests."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import imageio_ffmpeg
import numpy as np
import pandas as pd


def make_v3_dataset(
    root: Path,
    *,
    episode_ids: Sequence[int],
    lengths: Sequence[int],
    cameras: Sequence[str],
) -> Path:
    """Create a shared-shard, shared-video v3-shaped dataset containing only synthetic values."""
    if len(episode_ids) != len(lengths) or not episode_ids:
        raise ValueError("episode_ids and lengths must have the same nonzero length")
    if any(n <= 0 for n in lengths) or not cameras:
        raise ValueError("episodes need positive lengths and at least one camera")

    root.mkdir(parents=True, exist_ok=True)
    fps = 10
    features = {
        "observation.state": {"dtype": "float32", "shape": [2], "names": ["j0", "j1"]},
        "action": {"dtype": "float32", "shape": [2], "names": ["a0", "a1"]},
    }
    for camera in cameras:
        features[camera] = {"dtype": "video", "shape": [24, 32, 3], "names": None}
    info = {
        "codebase_version": "v3.0",
        "robot_type": "so101_follower",
        "fps": fps,
        "total_episodes": len(episode_ids),
        "total_frames": sum(lengths),
        "features": features,
        "data_path": "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet",
        "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4",
    }
    (root / "meta").mkdir(parents=True, exist_ok=True)
    (root / "meta" / "info.json").write_text(json.dumps(info), encoding="utf-8")

    rows: list[dict[str, object]] = []
    episodes: list[dict[str, object]] = []
    global_index = 0
    shared_video_frames = sum(lengths)
    for episode_id, length in zip(episode_ids, lengths, strict=True):
        from_t = global_index / fps
        for i in range(length):
            rows.append(
                {
                    "episode_index": episode_id,
                    "timestamp": i / fps,
                    "observation.state": [float(episode_id), float(i)],
                    "action": [float(i) / 10, float(i) / 20],
                }
            )
            global_index += 1
        episode = {
            "episode_index": episode_id,
            "length": length,
            "data/chunk_index": 0,
            "data/file_index": 0,
            "dataset_from_index": global_index - length,
            "dataset_to_index": global_index,
        }
        for camera in cameras:
            episode[f"videos/{camera}/chunk_index"] = 0
            episode[f"videos/{camera}/file_index"] = 0
            episode[f"videos/{camera}/from_timestamp"] = from_t
            episode[f"videos/{camera}/to_timestamp"] = global_index / fps
        episodes.append(episode)

    data_path = root / "data" / "chunk-000" / "file-000.parquet"
    data_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(data_path, index=False)
    episodes_path = root / "meta" / "episodes" / "chunk-000" / "file-000.parquet"
    episodes_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(episodes).to_parquet(episodes_path, index=False)

    for camera_index, camera in enumerate(cameras):
        video_path = root / "videos" / camera / "chunk-000" / "file-000.mp4"
        video_path.parent.mkdir(parents=True, exist_ok=True)
        writer = imageio_ffmpeg.write_frames(
            str(video_path), (32, 24), fps=fps, codec="libx264", pix_fmt_in="rgb24", macro_block_size=1
        )
        writer.send(None)
        try:
            for frame_index in range(shared_video_frames):
                frame = np.full((24, 32, 3), (frame_index * 13 + camera_index) % 256, dtype=np.uint8)
                writer.send(frame.tobytes())
        finally:
            writer.close()
    return root
