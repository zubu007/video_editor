"""Download a single YouTube video into the uploads directory via ``yt-dlp``.

The downloaded file is named ``{file_stem}.mp4`` so it slots into the same
``temp/uploads/{file_id}{ext}`` convention used by direct uploads, letting every
downstream feature (transcript, silence, render) treat it like any other source video.

Only single, on-demand videos are supported: playlists, livestreams, and videos longer
than :data:`MAX_DURATION_SECONDS` are rejected with a :class:`ValueError` so the caller
can surface a 400 rather than starting a doomed download.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

import yt_dlp

logger = logging.getLogger(__name__)

# Reject anything longer than this up front; long downloads/transcribes are rarely intended.
MAX_DURATION_SECONDS = 3 * 60 * 60  # 3 hours

# Prefer a progressive/merged MP4 so the result needs no remux gymnastics downstream.
_FORMAT = "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b"

ProgressCallback = Callable[[float], None]


class YouTubeDownloadError(Exception):
    """Raised when yt-dlp fails to fetch a video for reasons we cannot pre-validate."""


def _validate_single_video(info: dict[str, Any]) -> None:
    """Reject playlists, livestreams, and over-long videos.

    Args:
        info: The metadata dict returned by ``yt-dlp`` with ``download=False``.

    Raises:
        ValueError: If the URL is not a single, on-demand video within the duration cap.
    """
    if info.get("_type") == "playlist" or info.get("entries") is not None:
        raise ValueError(
            "Playlists are not supported; provide a link to a single video."
        )

    if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming"}:
        raise ValueError("Livestreams are not supported.")

    duration = info.get("duration")
    if duration is not None and duration > MAX_DURATION_SECONDS:
        raise ValueError(
            f"Video is too long ({int(duration)}s); the maximum is "
            f"{MAX_DURATION_SECONDS}s."
        )


def _make_progress_hook(
    on_progress: ProgressCallback,
) -> Callable[[dict[str, Any]], None]:
    """Adapt yt-dlp's progress dict into a simple 0..1 fraction callback."""

    def hook(status: dict[str, Any]) -> None:
        if status.get("status") != "downloading":
            return
        total = status.get("total_bytes") or status.get("total_bytes_estimate")
        downloaded = status.get("downloaded_bytes")
        if total and downloaded is not None:
            on_progress(max(0.0, min(1.0, downloaded / total)))

    return hook


def download_video(
    url: str,
    output_dir: Path,
    file_stem: str,
    *,
    on_progress: Optional[ProgressCallback] = None,
) -> dict[str, Any]:
    """Download a single YouTube video as ``{file_stem}.mp4`` under ``output_dir``.

    Args:
        url: The YouTube video URL.
        output_dir: Directory to write the downloaded file into (created if missing).
        file_stem: Filename stem to use (typically the project's ``file_id``).
        on_progress: Optional callback receiving download progress as a 0..1 fraction.

    Returns:
        A dict with ``path`` (the downloaded :class:`Path`), ``title``, and ``duration``.

    Raises:
        ValueError: If the URL is not a supported single video (see
            :func:`_validate_single_video`).
        YouTubeDownloadError: If yt-dlp fails to download the video.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Probe first so we can reject playlists/livestreams before fetching any media.
    probe_opts = {"quiet": True, "no_warnings": True, "noplaylist": True}
    try:
        with yt_dlp.YoutubeDL(probe_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise YouTubeDownloadError(f"Could not read video metadata: {exc}") from exc

    _validate_single_video(info)

    outtmpl = str(output_dir / f"{file_stem}.%(ext)s")
    download_opts: dict[str, Any] = {
        "format": _FORMAT,
        "outtmpl": outtmpl,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    if on_progress is not None:
        download_opts["progress_hooks"] = [_make_progress_hook(on_progress)]

    try:
        with yt_dlp.YoutubeDL(download_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as exc:
        raise YouTubeDownloadError(f"Download failed: {exc}") from exc

    dest_path = output_dir / f"{file_stem}.mp4"
    if not dest_path.exists():
        raise YouTubeDownloadError(
            "Download completed but the expected MP4 file was not produced."
        )

    return {
        "path": dest_path,
        "title": info.get("title") or "YouTube video",
        "duration": info.get("duration"),
    }
