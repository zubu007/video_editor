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
from pathlib import Path
from typing import Literal, Optional

import imageio_ffmpeg

from backend.features.captions import DEFAULT_STYLE, add_captions, add_text_captions
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


def caption_words_for_clip(
    words: list[dict],
    spans: list[tuple[float, float]],
    clip_start: float,
    clip_end: float,
) -> list[dict]:
    """Select and remap transcript words for a trimmed highlight clip.

    Keeps words whose midpoint falls inside one of the captions edits' spans
    *and* inside the clip, then shifts them onto the clip's timeline (the clip
    start becomes 0) and clamps them to the clip bounds. The contiguous-slice
    counterpart of :func:`backend.features.captions.remap.remap_words`.

    Args:
        words: Word entries ``{"start", "end", "word"}`` in source time.
        spans: ``(start, end)`` source-time spans the captions edits cover.
        clip_start: Clip start in source seconds.
        clip_end: Clip end in source seconds.

    Returns:
        list[dict]: The surviving words on the clip's timeline.
    """
    duration = clip_end - clip_start
    clipped: list[dict] = []
    for word in words:
        start, end = float(word["start"]), float(word["end"])
        midpoint = (start + end) / 2.0
        if not clip_start <= midpoint < clip_end:
            continue
        if not any(span_start <= midpoint < span_end for span_start, span_end in spans):
            continue
        clipped.append(
            {
                **word,
                "start": max(0.0, start - clip_start),
                "end": min(duration, end - clip_start),
            }
        )
    return clipped


def text_captions_for_clip(
    edits: list[dict], clip_start: float, clip_end: float
) -> list[dict]:
    """Select and remap text-caption edits for a trimmed highlight clip.

    Keeps captions whose midpoint falls inside the clip (mirroring the midpoint
    rule the project render uses), clamps their span to the clip and shifts it
    onto the clip's timeline, carrying the note's text and options.

    Args:
        edits: Plain-dict edit rows ``{"start", "end", "details"}`` where
            ``details`` holds ``text`` and optional ``position`` /
            ``reveal_seconds``.
        clip_start: Clip start in source seconds.
        clip_end: Clip end in source seconds.

    Returns:
        list[dict]: Caption blocks ready for
            :func:`backend.features.captions.add_text_captions`.
    """
    duration = clip_end - clip_start
    captions: list[dict] = []
    for edit in edits:
        details = edit.get("details") or {}
        text = str(details.get("text", ""))
        if not text.strip():
            continue
        start, end = float(edit["start"]), float(edit["end"])
        midpoint = (start + end) / 2.0
        if not clip_start <= midpoint < clip_end:
            continue
        captions.append(
            {
                "start": max(0.0, start - clip_start),
                "end": min(duration, end - clip_start),
                "text": text,
                "position": details.get("position"),
                "reveal_seconds": details.get("reveal_seconds"),
            }
        )
    return captions


def _ffmpeg_error_message(stderr: Optional[str]) -> str:
    """Turn ffmpeg's stderr into a short, user-facing job error.

    The generic "failed" message hid the actual cause (most damagingly a full
    disk, which reads as the app being broken); surface the recognisable cases
    and otherwise the last stderr line, which is where ffmpeg puts the reason.
    """
    text = stderr or ""
    if "No space left on device" in text:
        return (
            "The disk is full — the clip could not be written. Free up space "
            "(old uploads in temp/uploads are the usual culprit) and retry."
        )
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if lines:
        return f"Failed to create highlight clip: {lines[-1][:300]}"
    return "Failed to create highlight clip"


def _caption_words(
    video_path: str,
    captions_edits: list[dict],
    clip_start: float,
    clip_end: float,
) -> list[dict]:
    """Resolve the words a highlight clip's caption burn should draw.

    Words come from the first captions edit's saved ``details["words"]``,
    falling back to transcribing the source (as the project render does), then
    get filtered and remapped onto the clip's timeline.
    """
    if not captions_edits:
        return []
    details = captions_edits[0].get("details") or {}
    words = details.get("words")
    if not words:
        # Lazy import: transcription pulls in faster-whisper, which the plain
        # trim path never needs.
        from backend.features.transcript.extract import extract_transcript_as_words

        words = extract_transcript_as_words(str(video_path), "base")
    spans = [(float(edit["start"]), float(edit["end"])) for edit in captions_edits]
    return caption_words_for_clip(words, spans, clip_start, clip_end)


def run_highlight_job(
    job_id: str,
    video_path: str,
    start: float,
    end: float,
    output_path: str,
    output_filename: str,
    square: bool = False,
    captions_edits: Optional[list[dict]] = None,
    text_caption_edits: Optional[list[dict]] = None,
) -> None:
    """Trim ``source[start:end]`` into ``output_path`` with ffmpeg.

    Runs in a background thread. Re-encodes with a fast seek + veryfast preset
    (frame-accurate at the cut) and records the resulting download URL on the
    job, mirroring the other background-job workers. When caption edits overlap
    the clip, they are burned in as further ffmpeg passes (transcript captions
    first, then text notes on top), so the download matches what the project
    render would show over that stretch.

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
        captions_edits: Enabled ``captions`` edits as plain dicts
            ``{"start", "end", "details"}``; words/style come from the first
            edit's details, as in the project render.
        text_caption_edits: Enabled ``text_caption`` edits in the same shape.
    """
    update_job(job_id, status="running")
    duration = round(end - start, 3)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    try:
        # Resolve the caption burns up front (may transcribe the source when a
        # captions edit saved no words) so a caption-free clip trims straight to
        # its final path with no intermediate.
        burn_words = _caption_words(video_path, captions_edits or [], start, end)
        burn_notes = text_captions_for_clip(text_caption_edits or [], start, end)
        final_path = Path(output_path)
        trim_target = (
            final_path.with_name(f"precaption_{final_path.name}")
            if burn_words or burn_notes
            else final_path
        )

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
            str(trim_target),
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)

        # Chain the burn passes over the trimmed clip: each reads the previous
        # stage's file and the last one writes final_path. The ASS documents are
        # sized to the trimmed video, so this stays correct after a square crop
        # (bottom-positioned notes may overlap the composited minimap there).
        burn_source = trim_target
        if burn_words:
            details = (captions_edits or [{}])[0].get("details") or {}
            caption_out = (
                final_path.with_name(f"pretext_{final_path.name}")
                if burn_notes
                else final_path
            )
            add_captions(
                burn_source,
                burn_words,
                caption_out,
                style=details.get("style", DEFAULT_STYLE),
                max_words_per_line=details.get("max_words_per_line"),
            )
            burn_source.unlink(missing_ok=True)
            burn_source = caption_out
        if burn_notes:
            add_text_captions(burn_source, burn_notes, final_path)
            burn_source.unlink(missing_ok=True)

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
        update_job(job_id, status="error", error=_ffmpeg_error_message(e.stderr))
    except Exception as e:  # noqa: BLE001 - record any failure for the poller
        logger.error("Highlight job %s failed: %s", job_id, e)
        update_job(job_id, status="error", error=str(e))
