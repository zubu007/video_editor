"""ffprobe-based validation of source media for ranking clips."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from backend.features.ranking.schema import MediaInfo

MAX_SOURCE_SECONDS = 15 * 60
MAX_SOURCE_BYTES = 1024**3
PROBE_TIMEOUT_SECONDS = 60


def _parse_rate(value: str | None) -> float | None:
    if not value or "/" not in value:
        return None
    num, _, den = value.partition("/")
    try:
        return float(num) / float(den) if float(den) else None
    except ValueError:
        return None


def _parse_ratio(value: str | None) -> float | None:
    if not value or ":" not in value:
        return None
    num, _, den = value.partition(":")
    try:
        return float(num) / float(den) if float(den) and float(num) else None
    except ValueError:
        return None


def _rotation(stream: dict) -> int:
    """Return the display rotation in degrees (0, 90, 180 or 270)."""
    rotation = 0
    tags = stream.get("tags") or {}
    if "rotate" in tags:
        try:
            rotation = int(float(tags["rotate"]))
        except ValueError:
            rotation = 0
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            rotation = int(float(side["rotation"]))
    return rotation % 360


def probe_media(path: Path) -> MediaInfo:
    """Validate ``path`` as a usable video and return its display properties.

    Raises:
        ValueError: If the file is not a readable video with a usable duration.
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"Could not probe media: {exc}") from exc
    if result.returncode != 0:
        raise ValueError("The file is not a readable video.")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("The file is not a readable video.") from exc

    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError("The file has no video stream.")
    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    if width <= 0 or height <= 0:
        raise ValueError("The video has no usable dimensions.")
    sar = _parse_ratio(video.get("sample_aspect_ratio"))
    if sar and abs(sar - 1) > 0.01:
        width = max(1, round(width * sar))
    if _rotation(video) in (90, 270):
        width, height = height, width

    raw_duration = (data.get("format") or {}).get("duration") or video.get("duration")
    try:
        duration = float(raw_duration)
    except (TypeError, ValueError) as exc:
        raise ValueError("The video has no usable duration.") from exc
    if duration <= 0:
        raise ValueError("The video has no usable duration.")
    if duration > MAX_SOURCE_SECONDS:
        raise ValueError(
            f"The video is too long ({int(duration)}s); the limit is "
            f"{MAX_SOURCE_SECONDS}s."
        )

    return MediaInfo(
        duration=round(duration, 3),
        width=width,
        height=height,
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
        fps=_parse_rate(video.get("avg_frame_rate")),
    )
