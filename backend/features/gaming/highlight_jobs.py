"""In-memory job tracking for highlight-clip trimming.

Trimming a highlight re-encodes ``source[start:end]`` with ffmpeg, so its wall
time scales with the clip length and a long clip would otherwise block the
request for tens of seconds to minutes. This module runs the trim in a
background worker thread and exposes a thread-safe registry keyed by ``job_id``,
mirroring :mod:`backend.features.gaming.jobs`. Jobs are not persisted (lost on
restart), which is fine for the single-process deployment.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

import imageio_ffmpeg

from backend.features.gaming.reel_crop import REEL_OUTPUT_LABEL, reel_filter_for_video

logger = logging.getLogger(__name__)

JobStatus = Literal["pending", "running", "done", "error"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class HighlightJob:
    """State for a single highlight-clip job."""

    job_id: str
    file_id: str
    status: JobStatus = "pending"
    duration: float = 0.0
    filename: Optional[str] = None
    output_url: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)


_JOBS: dict[str, HighlightJob] = {}
_LOCK = threading.Lock()


def create_job(file_id: str) -> HighlightJob:
    """Create and register a new pending highlight job."""
    job = HighlightJob(job_id=str(uuid.uuid4()), file_id=file_id)
    with _LOCK:
        _JOBS[job.job_id] = job
    return job


def get_job(job_id: str) -> Optional[HighlightJob]:
    """Return a job by ID, or ``None`` if unknown."""
    with _LOCK:
        return _JOBS.get(job_id)


def update_job(job_id: str, **fields: object) -> None:
    """Apply field updates to a job and refresh its timestamp."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        for key, value in fields.items():
            setattr(job, key, value)
        job.updated_at = _utc_now()


def run_highlight_job(
    job_id: str,
    video_path: str,
    start: float,
    end: float,
    output_path: str,
    output_filename: str,
    square: bool = False,
) -> None:
    """Trim ``source[start:end]`` into ``output_path`` with ffmpeg.

    Runs in a background thread. Re-encodes with a fast seek + veryfast preset
    (frame-accurate at the cut) and records the resulting download URL on the
    job, mirroring the other background-job workers.

    Args:
        job_id: The job to report progress on.
        video_path: Source recording.
        start: Clip start in source seconds.
        end: Clip end in source seconds.
        output_path: Where to write the clip.
        output_filename: Basename used to build the download URL.
        square: Reframe the clip to a square reel — an equal-sided centre crop
            with the minimap and K/D/A readouts lifted from the discarded bands
            and composited back on (see :mod:`backend.features.gaming.reel_crop`).
            The reframe rides along in the same re-encode pass.
    """
    update_job(job_id, status="running")
    duration = round(end - start, 3)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    try:
        reframe: list[str] = []
        if square:
            # Probing and planning happen inside the try so an unusable source
            # (e.g. a portrait recording) lands on the job as an error message.
            reframe = [
                "-filter_complex",
                reel_filter_for_video(video_path),
                "-map",
                f"[{REEL_OUTPUT_LABEL}]",
                # filter_complex disables automatic stream selection; keep audio
                # if the source has any.
                "-map",
                "0:a?",
            ]
        command = [
            ffmpeg,
            "-y",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(video_path),
            "-t",
            f"{duration:.3f}",
            *reframe,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)
        update_job(
            job_id,
            status="done",
            duration=duration,
            filename=output_filename,
            output_url=f"/api/renders/{output_filename}",
        )
        logger.info(
            "Highlight job %s done: %s (%.2fs)", job_id, output_filename, duration
        )
    except subprocess.CalledProcessError as e:
        logger.error("Highlight job %s ffmpeg failed: %s", job_id, e.stderr)
        update_job(job_id, status="error", error="Failed to create highlight clip")
    except Exception as e:  # noqa: BLE001 - record any failure for the poller
        logger.error("Highlight job %s failed: %s", job_id, e)
        update_job(job_id, status="error", error=str(e))
