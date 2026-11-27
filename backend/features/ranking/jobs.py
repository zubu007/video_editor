"""In-memory registry for ranking download and render jobs.

Jobs are volatile: a restart drops them. Clip/render status shown to users is derived
from this registry plus persisted assets, so no spinner can outlive its worker.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

JobKind = Literal["download", "upload", "render", "preview"]
JobStatus = Literal["queued", "running", "done", "error", "cancelled"]
ACTIVE = {"queued", "running"}


@dataclass
class RankingJob:
    """State of one background operation."""

    job_id: str
    kind: JobKind
    project_id: str
    clip_id: str | None = None
    generation: int = 0
    revision: int | None = None
    status: JobStatus = "queued"
    phase: str = "Queued"
    progress: float = 0.0
    error: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Return the public JSON shape."""
        return {
            "job_id": self.job_id,
            "type": self.kind,
            "project_id": self.project_id,
            "clip_id": self.clip_id,
            "revision": self.revision,
            "status": self.status,
            "phase": self.phase,
            "progress": self.progress,
            "error": self.error,
            "result": self.result,
        }


_JOBS: dict[str, RankingJob] = {}
_LOCK = threading.Lock()


def create_job(kind: JobKind, project_id: str, **fields: Any) -> RankingJob:
    """Register a new queued job."""
    job = RankingJob(
        job_id=str(uuid.uuid4()), kind=kind, project_id=project_id, **fields
    )
    with _LOCK:
        _JOBS[job.job_id] = job
    return job


def get_job(job_id: str) -> RankingJob | None:
    """Return a job by id."""
    with _LOCK:
        return _JOBS.get(job_id)


def update_job(job_id: str, **fields: Any) -> None:
    """Update job fields; a cancelled job never reverts to another status."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        if job.status == "cancelled" and fields.get("status") not in (
            None,
            "cancelled",
        ):
            fields.pop("status")
        for key, value in fields.items():
            setattr(job, key, value)
        job.updated_at = datetime.now(UTC)


def jobs_for_project(project_id: str) -> list[RankingJob]:
    """Return all jobs of a project."""
    with _LOCK:
        return [j for j in _JOBS.values() if j.project_id == project_id]


def active_render(project_id: str) -> RankingJob | None:
    """Return an in-flight render/preview job for the project, if any."""
    for job in jobs_for_project(project_id):
        if job.kind in ("render", "preview") and job.status in ACTIVE:
            return job
    return None


def cancel_jobs(project_id: str, clip_id: str | None = None) -> int:
    """Request cancellation of active jobs (optionally only one clip's)."""
    count = 0
    with _LOCK:
        for job in _JOBS.values():
            if job.project_id != project_id or job.status not in ACTIVE:
                continue
            if clip_id is not None and job.clip_id != clip_id:
                continue
            job.cancel_event.set()
            job.status = "cancelled"
            job.phase = "Cancelled"
            count += 1
    return count


def cancel_job(job_id: str) -> RankingJob | None:
    """Cancel one job by id."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is not None and job.status in ACTIVE:
            job.cancel_event.set()
            job.status = "cancelled"
            job.phase = "Cancelled"
        return job
