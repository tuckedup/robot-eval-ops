"""TrialRecorder: writes video.mp4 (H.264 via imageio-ffmpeg) + trace.jsonl and measures completeness.

Bootstrapped by the lead so adapters can code against it; ownership transfers to Data/storage.
Timestamps and states are exactly what callers pass in: this module never invents or repairs them.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from robotevalops.schemas import Provenance, RecordingSummary, TraceHeader, TraceRow


class TrialRecorder:
    """Usage: rec = TrialRecorder(out_dir, fps, state_names, action_names, provenance, frame_size=(w,h));
    rec.add(t, image_rgb_or_None, state_vec, action_vec) per control step; summary = rec.close(expected_steps)."""

    def __init__(
        self,
        out_dir: Path,
        fps: float,
        state_names: list[str],
        action_names: list[str],
        provenance: Provenance,
        frame_size: tuple[int, int] | None = (320, 240),
        video_kind: str = "rendered_simulator_frames",
    ) -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.fps = float(fps)
        self.frame_size = frame_size
        self.video_kind = video_kind
        self._rows = 0
        self._frames = 0
        self._closed = False
        self._trace = open(self.out_dir / "trace.jsonl", "w", encoding="utf-8")  # noqa: SIM115
        header = TraceHeader(
            state_names=state_names, action_names=action_names, fps=self.fps, provenance=provenance
        )
        self._trace.write(header.model_dump_json() + "\n")
        self._writer = None
        if frame_size is not None:
            import imageio_ffmpeg

            self._writer = imageio_ffmpeg.write_frames(
                str(self.out_dir / "video.mp4"), frame_size, fps=self.fps, codec="libx264",
                pix_fmt_in="rgb24", macro_block_size=1, quality=7,
            )
            self._writer.send(None)

    def add(self, t: float, image: np.ndarray | None, state: list[float], action: list[float]) -> None:
        if self._closed:
            raise RuntimeError("recorder is closed")
        row = TraceRow(i=self._rows, t=float(t), state=[float(x) for x in state],
                       action=[float(x) for x in action])
        # allow_nan=True is intentional: real non-finite values must reach QA, not be hidden here.
        self._trace.write(json.dumps(row.model_dump(), allow_nan=True) + "\n")
        self._rows += 1
        if self._writer is not None and image is not None:
            w, h = self.frame_size  # type: ignore[misc]
            arr = np.ascontiguousarray(image[..., :3], dtype=np.uint8)
            if arr.shape[0] != h or arr.shape[1] != w:
                raise ValueError(f"frame shape {arr.shape} != configured {(h, w, 3)}")
            self._writer.send(arr.tobytes())
            self._frames += 1

    def close(self, expected_steps: int | None = None) -> RecordingSummary:
        if not self._closed:
            self._closed = True
            self._trace.flush()
            self._trace.close()
            if self._writer is not None:
                self._writer.close()
        expected = expected_steps if expected_steps is not None else self._rows
        completeness = (self._frames / expected) if (expected and self._writer is not None) else 0.0
        if self._writer is None and expected:
            completeness = self._rows / expected
        return RecordingSummary(
            video_relpath="video.mp4" if self._writer is not None else None,
            trace_relpath="trace.jsonl",
            frames_expected=int(expected),
            frames_written=self._frames,
            trace_rows=self._rows,
            fps=self.fps,
            completeness=float(min(1.0, completeness)) if math.isfinite(completeness) else 0.0,
            video_kind=self.video_kind,
        )
