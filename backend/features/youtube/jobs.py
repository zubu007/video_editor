"""In-memory job tracking for long-running YouTube download tasks.

Fetching a video can take from seconds to minutes, so downloads run in a background worker
thread. This module provides a minimal, thread-safe registry of job status keyed by
``job_id``, mirroring :mod:`backend.features.caption_removal.jobs`. Jobs are intentionally
not persisted; they are lost on server restart, which is acceptable for the current
single-process deployment.

When a download finishes, the worker performs the same persistence as a direct upload --
it creates a :class:`~backend.storage.database.MediaAsset` (and a
:class:`~backend.storage.database.Project` if one was not supplied) -- so on success the
job exposes ``file_id`` / ``project_id`` / ``media_asset_id`` and the client proceeds
exactly as it would after ``POST /api/video/upload``.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from sqlmodel import Session

from backend.features.youtube.download import download_video
from backend.storage.database import (
    MediaAsset,
    Project,
    engine,
    get_project,
    touch_project,
)

logger = logging.getLogger(__name__)

JobStatus = Literal["pending", "running", "done", "error"]


def _utc_now() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(timezone.utc)


@dataclass
class DownloadJob:
    """State for a single YouTube download job."""

    job_id: str
    url: str
    status: JobStatus = "pending"
    progress: float = 0.0
    file_id: Optional[str] = None
    project_id: Optional[str] = None
    media_asset_id: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)


_JOBS: dict[str, DownloadJob] = {}
_LOCK = threading.Lock()


def create_job(url: str) -> DownloadJob:
    """Create and register a new pending download job."""
    job = DownloadJob(job_id=str(uuid.uuid4()), url=url)
    with _LOCK:
        _JOBS[job.job_id] = job
    return job


def get_job(job_id: str) -> Optional[DownloadJob]:
    """Return a job by ID, or ``None`` if unknown."""
    with _LOCK:
        return _JOBS.get(job_id)


def _update(job_id: str, **fields: object) -> None:
    """Apply field updates to a job and refresh its timestamp."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        for key, value in fields.items():
            setattr(job, key, value)
        job.updated_at = _utc_now()


def _persist_media_asset(
    *,
    file_id: str,
    file_path: Path,
    title: str,
    duration: float | None,
    project_id: str | None,
    project_name: str | None,
) -> tuple[str, str]:
    """Create the Project (if needed) and MediaAsset for a finished download.

    Returns:
        A ``(project_id, media_asset_id)`` tuple.

    Raises:
        ValueError: If ``project_id`` is supplied but no such project exists.
    """
    file_url = f"/api/video/{file_id}"
    size = file_path.stat().st_size

    with Session(engine) as session:
        if project_id:
            project = get_project(session, project_id)
            if project is None:
                raise ValueError(f"Project not found: {project_id}")
        else:
            project = Project(name=project_name or title)
            session.add(project)
            session.commit()
            session.refresh(project)

        media_asset = MediaAsset(
            project_id=project.id,
            file_id=file_id,
            filename=f"{title}.mp4",
            file_url=file_url,
            size=size,
            duration=duration,
        )
        session.add(media_asset)
        touch_project(session, project)
        session.commit()
        session.refresh(media_asset)
        return project.id, media_asset.id


def run_download_job(
    job_id: str,
    url: str,
    file_id: str,
    output_dir: str,
    *,
    project_id: Optional[str] = None,
    project_name: Optional[str] = None,
) -> None:
    """Execute a YouTube download job, updating its status as it progresses.

    Intended to run in a background worker thread. All exceptions are caught and recorded
    on the job as an ``error`` status so the poller can surface them. On success the job's
    ``file_id`` / ``project_id`` / ``media_asset_id`` are populated.
    """
    _update(job_id, status="running")
    out_dir = Path(output_dir)

    try:
        result = download_video(
            url,
            out_dir,
            file_id,
            on_progress=lambda fraction: _update(job_id, progress=fraction),
        )
    except Exception as exc:  # noqa: BLE001 - record any failure for the poller
        logger.error("YouTube download job %s failed: %s", job_id, exc)
        _update(job_id, status="error", error=str(exc))
        return

    try:
        resolved_project_id, media_asset_id = _persist_media_asset(
            file_id=file_id,
            file_path=result["path"],
            title=result["title"],
            duration=result["duration"],
            project_id=project_id,
            project_name=project_name,
        )
    except Exception as exc:  # noqa: BLE001 - record any failure for the poller
        logger.error("Persisting download job %s failed: %s", job_id, exc)
        # The media downloaded but could not be registered; clean up the orphan file.
        downloaded = result.get("path")
        if isinstance(downloaded, Path) and downloaded.exists():
            downloaded.unlink()
        _update(job_id, status="error", error=str(exc))
        return

    _update(
        job_id,
        status="done",
        progress=1.0,
        file_id=file_id,
        project_id=resolved_project_id,
        media_asset_id=media_asset_id,
    )
    logger.info("YouTube download job %s completed (file_id=%s)", job_id, file_id)
