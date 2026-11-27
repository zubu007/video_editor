"""Safe single-clip import from YouTube / Instagram Reels links and local uploads."""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yt_dlp

from backend.features.ranking.media import MAX_SOURCE_BYTES, MAX_SOURCE_SECONDS

logger = logging.getLogger(__name__)

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}
INSTAGRAM_HOSTS = {"instagram.com", "www.instagram.com"}
INSTAGRAM_PATHS = ("/reel/", "/reels/", "/p/", "/tv/")
_FORMAT = "bv*[height<=1920][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b"


class DownloadCancelled(Exception):
    """The job was cancelled while downloading."""


class DownloadError(Exception):
    """A user-facing download failure."""


def validate_source_url(url: str) -> str:
    """Validate ``url`` against the provider allow-list and return the provider.

    Only public YouTube and Instagram hosts are accepted, which also rules out
    localhost, private-network targets and non-HTTP schemes.

    Raises:
        ValueError: If the URL is not an allowed single-video link.
    """
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http(s) links are supported.")
    if parsed.username or parsed.password:
        raise ValueError("Links with embedded credentials are not allowed.")
    if parsed.port not in (None, 80, 443):
        raise ValueError("Links with custom ports are not allowed.")
    host = (parsed.hostname or "").lower()
    if host in YOUTUBE_HOSTS:
        if parsed.path.startswith("/playlist"):
            raise ValueError("Playlists are not supported; link one video.")
        return "youtube"
    if host in INSTAGRAM_HOSTS:
        if not parsed.path.startswith(INSTAGRAM_PATHS):
            raise ValueError("Only public Instagram Reel links are supported.")
        return "instagram"
    raise ValueError(
        "Unsupported site. Use a YouTube/Shorts or Instagram Reel link, or upload "
        "the video instead."
    )


def explain_failure(message: str) -> str:
    """Translate a yt-dlp failure into an actionable message."""
    lowered = message.lower()
    if any(k in lowered for k in ("private", "login", "sign in", "cookies")):
        return "This video is private or needs a login. Upload the file instead."
    if "429" in lowered or ("rate" in lowered and "limit" in lowered):
        return "The site is rate-limiting requests. Retry in a few minutes."
    if "not available in your country" in lowered or "geo" in lowered:
        return "This video is region-restricted. Upload the file instead."
    if any(k in lowered for k in ("removed", "deleted", "unavailable", "404")):
        return "This video was removed or is unavailable."
    return f"Download failed: {message[:300]}"


def download_clip(
    url: str,
    output_dir: Path,
    stem: str,
    cancel_event: threading.Event,
    on_progress: Callable[[float], None],
) -> dict[str, Any]:
    """Download one video as ``{stem}.mp4`` under ``output_dir``.

    Raises:
        ValueError: On disallowed URLs or videos beyond the limits.
        DownloadCancelled: If ``cancel_event`` is set.
        DownloadError: For provider failures.
    """
    validate_source_url(url)
    output_dir.mkdir(parents=True, exist_ok=True)
    common: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 3,
    }
    try:
        with yt_dlp.YoutubeDL(common) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(explain_failure(str(exc))) from exc
    if info.get("_type") == "playlist" or info.get("entries") is not None:
        raise ValueError("Playlists are not supported; link one video.")
    if info.get("is_live"):
        raise ValueError("Livestreams are not supported.")
    duration = info.get("duration")
    if duration and duration > MAX_SOURCE_SECONDS:
        raise ValueError(
            f"Video is too long ({int(duration)}s); the limit is {MAX_SOURCE_SECONDS}s."
        )

    def hook(status: dict[str, Any]) -> None:
        if cancel_event.is_set():
            raise DownloadCancelled()
        if status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate")
            done = status.get("downloaded_bytes")
            if total and done is not None:
                on_progress(max(0.0, min(1.0, done / total)))

    options = {
        **common,
        "format": _FORMAT,
        "outtmpl": str(output_dir / f"{stem}.%(ext)s"),
        "merge_output_format": "mp4",
        "max_filesize": MAX_SOURCE_BYTES,
        "progress_hooks": [hook],
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])
    except DownloadCancelled:
        cleanup_partials(output_dir, stem)
        raise
    except yt_dlp.utils.DownloadError as exc:
        cleanup_partials(output_dir, stem)
        if isinstance(exc.exc_info and exc.exc_info[1], DownloadCancelled):
            raise DownloadCancelled() from exc
        raise DownloadError(explain_failure(str(exc))) from exc

    result = output_dir / f"{stem}.mp4"
    if not result.exists():
        cleanup_partials(output_dir, stem)
        raise DownloadError(
            f"The video exceeds the {MAX_SOURCE_BYTES // 1024**2} MB limit or could "
            "not be produced."
        )
    return {"path": result, "title": info.get("title") or ""}


def cleanup_partials(output_dir: Path, stem: str) -> None:
    """Remove any partial files produced for ``stem``."""
    for path in output_dir.glob(f"{stem}.*"):
        path.unlink(missing_ok=True)


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]")


def safe_display_name(filename: str) -> str:
    """Return a harmless display filename."""
    return _SAFE_NAME.sub("_", Path(filename).name)[:120] or "clip.mp4"
