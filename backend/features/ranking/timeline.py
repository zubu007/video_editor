"""Deterministic frame scheduling and name-reveal state.

The frontend mirrors these rules in ``frontend/src/utils/rankingTimeline.js``; keep the
two in sync. Intervals are half-open ``[start_frame, end_frame)``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from backend.features.ranking.schema import FPS, RankingDocument


@dataclass(frozen=True)
class Segment:
    """One clip's slot on the output timeline."""

    clip_id: str
    start_frame: int
    frames: int

    @property
    def end_frame(self) -> int:
        """Return the exclusive end frame."""
        return self.start_frame + self.frames


@dataclass(frozen=True)
class Schedule:
    """The ordered output timeline."""

    segments: tuple[Segment, ...]

    @property
    def total_frames(self) -> int:
        """Return the total number of output frames."""
        return self.segments[-1].end_frame if self.segments else 0

    @property
    def total_seconds(self) -> float:
        """Return the total duration in seconds."""
        return self.total_frames / FPS


def frames_for(trim_in: float, trim_out: float) -> int:
    """Quantise a trimmed duration to output frames (round-half-up, minimum 1)."""
    return max(1, math.floor((trim_out - trim_in) * FPS + 0.5))


def build_schedule(doc: RankingDocument) -> Schedule:
    """Build the frame schedule in playback order.

    Raises:
        ValueError: If a clip has no usable trim range.
    """
    segments: list[Segment] = []
    cursor = 0
    for clip in doc.in_playback_order():
        trim_out = clip.resolved_out
        if trim_out is None:
            raise ValueError(f"Clip '{clip.name or clip.id}' has no source yet")
        if trim_out - clip.trim_in < 0.5 / FPS:
            raise ValueError(
                f"Clip '{clip.name or clip.id}' trim is shorter than one frame"
            )
        frames = frames_for(clip.trim_in, trim_out)
        segments.append(Segment(clip.id, cursor, frames))
        cursor += frames
    return Schedule(tuple(segments))


def segment_index_at(schedule: Schedule, frame: int) -> int:
    """Return the active segment index at ``frame`` (clamped to the last frame)."""
    if not schedule.segments:
        raise ValueError("Empty schedule")
    frame = max(0, min(frame, schedule.total_frames - 1))
    for index, segment in enumerate(schedule.segments):
        if segment.start_frame <= frame < segment.end_frame:
            return index
    return len(schedule.segments) - 1


def revealed_clip_ids(schedule: Schedule, frame: int) -> list[str]:
    """Return ids of clips whose names are visible at ``frame``.

    Computed purely from time: every clip that started at or before ``frame``.
    """
    index = segment_index_at(schedule, frame)
    return [segment.clip_id for segment in schedule.segments[: index + 1]]
