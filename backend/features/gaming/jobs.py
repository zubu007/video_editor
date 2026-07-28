"""In-memory job tracking for Dota 2 death detection.

Scanning a full match's HUD (decode at 1 fps + per-frame signal work) takes
around a minute or two, so detection runs in a background worker thread. This
module is a minimal, thread-safe registry keyed by ``job_id`` mirroring
:mod:`backend.features.video_cutter.jobs`; the worker ``run_death_detect_job``
lives here since it only needs the detector, not the route layer. Jobs are not
persisted (lost on restart), which is fine for the single-process deployment.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

from backend.features.gaming.death_detect import detect_gaming_markers

logger = logging.getLogger(__name__)

JobStatus = Literal["pending", "running", "done", "error"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class DeathDetectJob:
    """State for a single death-detection job."""

    job_id: str
    file_id: str
    status: JobStatus = "pending"
    intervals: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    player_slot: Optional[int] = None
    confidence: Optional[float] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)


_JOBS: dict[str, DeathDetectJob] = {}
_LOCK = threading.Lock()


def create_job(file_id: str) -> DeathDetectJob:
    """Create and register a new pending death-detection job."""
    job = DeathDetectJob(job_id=str(uuid.uuid4()), file_id=file_id)
    with _LOCK:
        _JOBS[job.job_id] = job
    return job


def get_job(job_id: str) -> Optional[DeathDetectJob]:
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


def run_death_detect_job(
    job_id: str,
    video_path: str,
    team: str = "radiant",
    player_slot: Optional[int] = None,
    detect_kda: bool = True,
) -> None:
    """Detect death intervals and K/D/A markers, recording them on the job.

    A single HUD scan yields both the player's dead intervals (saved as cuts) and
    the kills/deaths/assists event markers for the play bar. When ``player_slot``
    is ``None`` the slot is auto-identified first (so the resolved slot and its
    confidence can drive the UI's slot selector); otherwise the caller's manual
    override is used verbatim. ``detect_kda`` toggles the K/A OCR pass.
    """
    update_job(job_id, status="running")
    try:
        result = detect_gaming_markers(
            video_path,
            team=team,
            player_slot=player_slot,
            detect_kda=detect_kda,
        )
        update_job(
            job_id,
            status="done",
            intervals=result["intervals"],
            events=result["events"],
            player_slot=result["player_slot"],
            confidence=result["confidence"],
        )
        logger.info(
            "Death detection job %s done: slot %s, %d deaths, %d events",
            job_id,
            result["player_slot"],
            len(result["intervals"]),
            len(result["events"]),
        )
    except Exception as e:  # noqa: BLE001 - record any failure for the poller
        logger.error("Death detection job %s failed: %s", job_id, e)
        update_job(job_id, status="error", error=str(e))
