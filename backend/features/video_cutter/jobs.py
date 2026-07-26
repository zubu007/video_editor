"""In-memory job tracking for long-running project render tasks.

Rendering a project (MoviePy/ffmpeg encode, plus optional stock-footage download,
diagram overlays, and a caption burn pass) can take from seconds to minutes, so it
runs in a background worker thread. This module is a minimal, thread-safe registry
of render status keyed by ``job_id``, mirroring
:mod:`backend.features.youtube.jobs`. Jobs are intentionally not persisted; they are
lost on server restart, which is acceptable for the current single-process
deployment.

The worker itself lives in :mod:`backend.app` (``_run_render_job``) so it can reuse
the route layer's edit-resolution helpers; this module only holds state and exposes
``create_job`` / ``get_job`` / ``update_job``.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

JobStatus = Literal["pending", "running", "done", "error"]


def _utc_now() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(timezone.utc)


@dataclass
class RenderJob:
    """State for a single project render job."""

    job_id: str
    project_id: str
    status: JobStatus = "pending"
    progress: float = 0.0
    output_url: Optional[str] = None
    filename: Optional[str] = None
    applied_edits: Optional[int] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)


_JOBS: dict[str, RenderJob] = {}
_LOCK = threading.Lock()


def create_job(project_id: str) -> RenderJob:
    """Create and register a new pending render job."""
    job = RenderJob(job_id=str(uuid.uuid4()), project_id=project_id)
    with _LOCK:
        _JOBS[job.job_id] = job
    return job


def get_job(job_id: str) -> Optional[RenderJob]:
    """Return a job by ID, or ``None`` if unknown."""
    with _LOCK:
        return _JOBS.get(job_id)


def update_job(job_id: str, **fields: object) -> None:
    """Apply field updates to a job and refresh its timestamp.

    Progress updates arrive at frame cadence, so this is deliberately cheap and
    lock-guarded. Unknown ``job_id`` values are ignored.
    """
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        for key, value in fields.items():
            setattr(job, key, value)
        job.updated_at = _utc_now()
