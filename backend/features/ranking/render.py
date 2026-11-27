"""Render a ranking composition to a portrait MP4 with ffmpeg.

Each clip is normalised to an exact frame count (video as H.264 segments, audio as
48 kHz stereo PCM), the segments are concatenated losslessly, and a single AAC encode
produces the final file. Reveal state per segment comes from the shared schedule, so
frame boundaries are identical to the preview.
"""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session

from backend.features.ranking import jobs, store
from backend.features.ranking.compose import Issue, layout_issues, render_overlay
from backend.features.ranking.schema import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    FPS,
    Clip,
    RankingDocument,
)
from backend.features.ranking.timeline import (
    Schedule,
    build_schedule,
    revealed_clip_ids,
)

logger = logging.getLogger(__name__)

WORK_DIR = Path("temp/ranking_work")
COMMAND_TIMEOUT_SECONDS = 30 * 60
SAMPLE_RATE = 48000
PREVIEW_SIZE = (540, 960)
DURATION_TOLERANCE_SECONDS = 0.3


class RenderCancelled(Exception):
    """The render job was cancelled."""


class RenderError(Exception):
    """The render failed; the message is user-facing."""


def export_issues(session: Session, doc: RankingDocument) -> list[Issue]:
    """Return every reason the composition cannot be exported yet."""
    issues: list[Issue] = []
    for clip in doc.in_playback_order():
        field = f"clip:{clip.id}"
        label = clip.name.strip() or f"Rank {clip.rank}"
        if not clip.name.strip():
            issues.append(Issue(field, f"Rank {clip.rank} needs a name."))
        if not store.clip_media(session, clip.asset_id)["available"] or not clip.media:
            issues.append(
                Issue(field, f"{label}: source video is missing or not ready.")
            )
            continue
        trim_out = clip.resolved_out
        assert trim_out is not None
        if trim_out > clip.media.duration + 0.05:
            issues.append(
                Issue(field, f"{label}: trim end is past the end of the video.")
            )
        elif trim_out - clip.trim_in < 1 / FPS:
            issues.append(Issue(field, f"{label}: trim is shorter than one frame."))
    issues.extend(layout_issues(doc))
    return issues


def _run(
    command: list[str],
    cancel_event: threading.Event,
    log_path: Path,
) -> None:
    """Run ffmpeg, polling for cancellation; raise ``RenderError`` on failure."""
    with log_path.open("wb") as log:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=log)
        waited = 0.0
        while True:
            try:
                process.wait(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                waited += 0.25
                if cancel_event.is_set():
                    process.kill()
                    process.wait()
                    raise RenderCancelled() from None
                if waited > COMMAND_TIMEOUT_SECONDS:
                    process.kill()
                    process.wait()
                    raise RenderError("ffmpeg timed out.") from None
    if process.returncode != 0:
        tail = log_path.read_text(errors="replace")[-600:]
        logger.error("ffmpeg failed: %s", tail)
        raise RenderError("ffmpeg failed while rendering a clip.")


def _even(value: float) -> int:
    return max(2, int(math.ceil(value / 2) * 2))


def _video_filter(clip: Clip, doc: RankingDocument, scale_out: bool) -> str:
    """Build the filter graph placing the trimmed clip into the canvas."""
    assert clip.media is not None
    vx, vy, vw, vh = doc.canvas.viewport
    src_w, src_h = clip.media.width, clip.media.height
    chain = [f"[0:v]fps={FPS}", "scale=trunc(iw*sar):ih", "setsar=1"]
    if clip.fit == "fill":
        scale = max(vw / src_w, vh / src_h) * clip.zoom
        sw, sh = max(_even(src_w * scale), vw), max(_even(src_h * scale), vh)
        crop_x = round((sw - vw) * clip.focal_x)
        crop_y = round((sh - vh) * clip.focal_y)
        chain += [f"scale={sw}:{sh}:flags=bicubic", f"crop={vw}:{vh}:{crop_x}:{crop_y}"]
    else:
        scale = min(vw / src_w, vh / src_h)
        sw, sh = min(_even(src_w * scale), vw), min(_even(src_h * scale), vh)
        bg = clip.fit_background.replace("#", "0x")
        chain += [
            f"scale={sw}:{sh}:flags=bicubic",
            f"pad={vw}:{vh}:{(vw - sw) // 2}:{(vh - sh) // 2}:color={bg}",
        ]
    chain += ["tpad=stop_mode=clone:stop_duration=3", "format=yuv420p"]
    canvas_bg = doc.canvas.background.replace("#", "0x")
    graph = (
        ",".join(chain)
        + "[clip];"
        + f"color=c={canvas_bg}:s={CANVAS_WIDTH}x{CANVAS_HEIGHT}:r={FPS}[bg];"
        + f"[bg][clip]overlay={vx}:{vy}[base];"
        + "[base][1:v]overlay=0:0:format=auto,format=yuv420p"
    )
    if scale_out:
        graph += f",scale={PREVIEW_SIZE[0]}:{PREVIEW_SIZE[1]}:flags=bicubic"
    return graph + "[out]"


def _check_cancel(job_id: str, event: threading.Event) -> None:
    if event.is_set():
        raise RenderCancelled()


def probe_output(path: Path, expected_seconds: float, preview: bool) -> None:
    """Verify the finished file's streams, size and duration.

    Raises:
        RenderError: If anything is off.
    """
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
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        raise RenderError("The rendered file could not be read back.")
    data = json.loads(result.stdout)
    streams = {s["codec_type"]: s for s in data["streams"]}
    video, audio = streams.get("video"), streams.get("audio")
    if video is None or audio is None:
        raise RenderError("The rendered file is missing a video or audio stream.")
    expected = PREVIEW_SIZE if preview else (CANVAS_WIDTH, CANVAS_HEIGHT)
    if (video["width"], video["height"]) != expected or video["codec_name"] != "h264":
        raise RenderError("The rendered video has unexpected dimensions or codec.")
    duration = float(data["format"]["duration"])
    if abs(duration - expected_seconds) > DURATION_TOLERANCE_SECONDS:
        raise RenderError(
            f"Rendered duration {duration:.2f}s differs from {expected_seconds:.2f}s."
        )


def render_composition(
    bind: Engine,
    doc: RankingDocument,
    job_id: str,
    output_path: Path,
    *,
    preview: bool = False,
    on_progress: Callable[[str, float], None] | None = None,
) -> Path:
    """Render the frozen ``doc`` to ``output_path`` (atomically promoted).

    Raises:
        RenderCancelled: If the job is cancelled.
        RenderError: On failure.
    """
    job = jobs.get_job(job_id)
    cancel = job.cancel_event if job else threading.Event()

    def report(phase: str, fraction: float) -> None:
        jobs.update_job(job_id, phase=phase, progress=min(1.0, fraction))
        if on_progress:
            on_progress(phase, fraction)

    try:
        schedule: Schedule = build_schedule(doc)
    except ValueError as exc:
        raise RenderError(str(exc)) from exc

    work = WORK_DIR / job_id
    work.mkdir(parents=True, exist_ok=True)
    partial = output_path.with_name(output_path.name + ".partial")
    try:
        clips = {c.id: c for c in doc.clips}
        count = len(schedule.segments)
        video_list: list[Path] = []
        audio_list: list[Path] = []
        crf, preset = ("30", "ultrafast") if preview else ("18", "veryfast")

        report("Preparing", 0.0)
        with Session(bind) as session:
            sources: dict[str, Path] = {}
            for clip in doc.clips:
                media = store.clip_media(session, clip.asset_id)
                path = store.find_media_path(media.get("file_id", ""))
                if path is None:
                    raise RenderError(f"Source for '{clip.name}' is missing.")
                sources[clip.id] = path

        for index, segment in enumerate(schedule.segments):
            _check_cancel(job_id, cancel)
            clip = clips[segment.clip_id]
            base = (index + 1) / count
            report(f"Rendering clip {index + 1} of {count}", 0.9 * index / count)
            overlay_path = work / f"overlay_{index}.png"
            render_overlay(
                doc,
                revealed_clip_ids(schedule, segment.start_frame),
                segment.clip_id,
            ).save(overlay_path)

            seconds = segment.frames / FPS
            source_seconds = (clip.resolved_out or 0) - clip.trim_in
            video_path = work / f"seg_{index}.mp4"
            _run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-ss",
                    f"{clip.trim_in:.6f}",
                    "-t",
                    f"{source_seconds:.6f}",
                    "-i",
                    str(sources[clip.id]),
                    "-loop",
                    "1",
                    "-framerate",
                    str(FPS),
                    "-i",
                    str(overlay_path),
                    "-filter_complex",
                    _video_filter(clip, doc, preview),
                    "-map",
                    "[out]",
                    "-an",
                    "-frames:v",
                    str(segment.frames),
                    "-r",
                    str(FPS),
                    "-c:v",
                    "libx264",
                    "-preset",
                    preset,
                    "-crf",
                    crf,
                    "-pix_fmt",
                    "yuv420p",
                    "-g",
                    str(FPS * 2),
                    str(video_path),
                ],
                cancel,
                work / f"seg_{index}.log",
            )
            video_list.append(video_path)

            audio_path = work / f"seg_{index}.wav"
            assert clip.media is not None
            if clip.media.has_audio and not clip.muted:
                audio_input = [
                    "-ss",
                    f"{clip.trim_in:.6f}",
                    "-t",
                    f"{source_seconds:.6f}",
                    "-i",
                    str(sources[clip.id]),
                    "-vn",
                    "-af",
                    f"volume={clip.volume:.3f},apad",
                ]
            else:
                audio_input = [
                    "-f",
                    "lavfi",
                    "-i",
                    f"anullsrc=r={SAMPLE_RATE}:cl=stereo",
                ]
            _run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    *audio_input,
                    "-t",
                    f"{seconds:.6f}",
                    "-ar",
                    str(SAMPLE_RATE),
                    "-ac",
                    "2",
                    "-c:a",
                    "pcm_s16le",
                    str(audio_path),
                ],
                cancel,
                work / f"seg_{index}_a.log",
            )
            audio_list.append(audio_path)
            report(f"Rendering clip {index + 1} of {count}", 0.9 * base)

        report("Finalizing", 0.92)
        _check_cancel(job_id, cancel)
        video_concat, audio_concat = work / "video.txt", work / "audio.txt"
        video_concat.write_text("".join(f"file '{p.resolve()}'\n" for p in video_list))
        audio_concat.write_text("".join(f"file '{p.resolve()}'\n" for p in audio_list))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        _run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(video_concat),
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(audio_concat),
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                str(SAMPLE_RATE),
                "-ac",
                "2",
                "-t",
                f"{schedule.total_seconds:.6f}",
                "-movflags",
                "+faststart",
                "-f",
                "mp4",
                str(partial),
            ],
            cancel,
            work / "final.log",
        )
        probe_output(partial, schedule.total_seconds, preview)
        _check_cancel(job_id, cancel)
        os.replace(partial, output_path)
        report("Done", 1.0)
        return output_path
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
