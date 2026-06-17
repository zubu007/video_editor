"""In-memory job tracking for long-running caption removal tasks.

Caption removal runs frame-by-frame inpainting and can take minutes, so it is executed in
a background worker thread. This module provides a minimal, thread-safe registry of job
status keyed by ``job_id``. Jobs are intentionally not persisted; they are lost on server
restart, which is acceptable for the current single-process deployment.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

from backend.features.caption_removal.remove import DEFAULT_MODE, remove_captions

logger = logging.getLogger(__name__)

JobStatus = Literal["pending", "running", "done", "error"]


def _utc_now() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(timezone.utc)


@dataclass
class CaptionJob:
    """State for a single caption removal job."""

    job_id: str
    file_id: str
    output_filename: str
    status: JobStatus = "pending"
    error: Optional[str] = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)


_JOBS: dict[str, CaptionJob] = {}
_LOCK = threading.Lock()


def create_job(file_id: str, output_filename: str) -> CaptionJob:
    """Create and register a new pending job."""
    job = CaptionJob(
        job_id=str(uuid.uuid4()),
        file_id=file_id,
        output_filename=output_filename,
    )
    with _LOCK:
        _JOBS[job.job_id] = job
    return job


def get_job(job_id: str) -> Optional[CaptionJob]:
    """Return a job by ID, or ``None`` if unknown."""
    with _LOCK:
        return _JOBS.get(job_id)


def _set_status(job_id: str, status: JobStatus, error: Optional[str] = None) -> None:
    """Update a job's status and timestamp."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job.status = status
        job.error = error
        job.updated_at = _utc_now()


def run_caption_removal_job(
    job_id: str,
    video_path: str,
    output_path: str,
    *,
    mode: str = DEFAULT_MODE,
    use_gpu: bool = False,
) -> None:
    """Execute a caption removal job, updating its status as it progresses.

    Intended to run in a background worker thread. All exceptions are caught and recorded
    on the job as an ``error`` status so the poller can surface them.
    """
    _set_status(job_id, "running")
    try:
        remove_captions(video_path, output_path, mode=mode, use_gpu=use_gpu)
        _set_status(job_id, "done")
    except Exception as exc:  # noqa: BLE001 - record any failure for the poller
        logger.error("Caption removal job %s failed: %s", job_id, exc)
        _set_status(job_id, "error", error=str(exc))
