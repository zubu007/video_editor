"""In-memory job tracking for word-level transcription.

Transcribing a full-length recording with faster-whisper on CPU can take many
minutes, so it runs in a background worker thread and its progress is polled
instead of blocking the upload request. This module is a minimal, thread-safe
registry keyed by ``job_id`` mirroring
:mod:`backend.features.gaming.jobs`; the worker ``run_transcript_job`` lives
here since it only needs the extractor, not the route layer. Jobs are not
persisted (lost on restart), which is fine for the single-process deployment.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

from backend.features.transcript.extract import extract_transcript_as_words

logger = logging.getLogger(__name__)

JobStatus = Literal["pending", "running", "done", "error"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class TranscriptJob:
    """State for a single transcription job."""

    job_id: str
    file_id: str
    model_size: str = "base"
    status: JobStatus = "pending"
    progress: float = 0.0
    words: list[dict] = field(default_factory=list)
    error: Optional[str] = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)


_JOBS: dict[str, TranscriptJob] = {}
_LOCK = threading.Lock()


def create_job(file_id: str, model_size: str = "base") -> TranscriptJob:
    """Create and register a new pending transcription job."""
    job = TranscriptJob(
        job_id=str(uuid.uuid4()), file_id=file_id, model_size=model_size
    )
    with _LOCK:
        _JOBS[job.job_id] = job
    return job


def get_job(job_id: str) -> Optional[TranscriptJob]:
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


def run_transcript_job(
    job_id: str,
    video_path: str,
    model_size: str = "base",
) -> None:
    """Transcribe ``video_path`` to words, recording progress on the job.

    Runs in a background thread. The extractor reports a 0.0-1.0 fraction as it
    advances through the audio, which is written back to the job so the frontend
    can drive a progress bar while polling.
    """
    update_job(job_id, status="running", progress=0.0)
    try:

        def on_progress(fraction: float) -> None:
            update_job(job_id, progress=fraction)

        words = extract_transcript_as_words(
            video_path, model_size, on_progress=on_progress
        )
        update_job(job_id, status="done", progress=1.0, words=words)
        logger.info("Transcript job %s done: %d words", job_id, len(words))
    except Exception as e:  # noqa: BLE001 - record any failure for the poller
        logger.error("Transcript job %s failed: %s", job_id, e)
        update_job(job_id, status="error", error=str(e))
