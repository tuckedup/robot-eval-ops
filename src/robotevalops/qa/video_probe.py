"""Decode a video file and report real frame count and presentation times (PyAV first, OpenCV fallback).

Nothing is repaired or interpolated: ``times`` are the container's own frame timestamps, ``frames`` the number
of frames that actually decoded. A decode error is returned, never raised, so QA can flag it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class VideoProbe:
    frames: int = 0
    times: list[float] = field(default_factory=list)
    duration: float = 0.0  # last frame time + one frame interval
    width: int = 0
    height: int = 0
    backend: str = ""
    truncated: bool = False  # stopped at max_frames: counts are lower bounds
    error: str | None = None


def probe_video(path: str | Path, *, max_frames: int = 100_000) -> VideoProbe:
    path = Path(path)
    errors: list[str] = []
    try:
        import av  # noqa: F401
    except ImportError:
        errors.append("PyAV not installed")
    else:
        p = _probe_av(path, max_frames)
        if p.error is None:
            return p
        errors.append(f"av: {p.error}")
    try:
        import cv2  # noqa: F401
    except ImportError:
        errors.append("OpenCV not installed")
    else:
        p = _probe_cv2(path, max_frames)
        if p.error is None:
            return p
        errors.append(f"cv2: {p.error}")
    return VideoProbe(error="; ".join(errors))


def _probe_av(path: Path, max_frames: int) -> VideoProbe:
    import av

    out = VideoProbe(backend="av")
    try:
        with av.open(str(path)) as container:
            if not container.streams.video:
                out.error = "no video stream"
                return out
            stream = container.streams.video[0]
            out.width, out.height = stream.codec_context.width, stream.codec_context.height
            rate = float(stream.average_rate) if stream.average_rate else 0.0
            for i, frame in enumerate(container.decode(stream)):
                if i == 0:
                    frame.to_ndarray(format="rgb24")  # force a real pixel decode of the first frame
                if frame.pts is None or stream.time_base is None:
                    t = i / rate if rate else float(i)
                else:
                    t = float(frame.pts * stream.time_base)
                out.times.append(t)
                if len(out.times) >= max_frames:
                    out.truncated = True
                    break
            out.frames = len(out.times)
            if out.frames:
                step = (
                    (out.times[-1] - out.times[0]) / (out.frames - 1)
                    if out.frames > 1
                    else (1 / rate if rate else 0)
                )
                out.duration = out.times[-1] + step
    except Exception as exc:  # noqa: BLE001 - corrupt/unsupported media
        out.error = f"{type(exc).__name__}: {exc}"
    return out


def _probe_cv2(path: Path, max_frames: int) -> VideoProbe:
    import cv2

    out = VideoProbe(backend="cv2")
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            out.error = "cannot open"
            return out
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 0.0
        out.width, out.height = (
            int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )
        while True:
            ok, _ = cap.read()
            if not ok:
                break
            out.times.append(len(out.times) / fps if fps else float(len(out.times)))
            if len(out.times) >= max_frames:
                out.truncated = True
                break
        out.frames = len(out.times)
        out.duration = out.frames / fps if fps else 0.0
    finally:
        cap.release()
    return out
