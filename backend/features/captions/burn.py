"""Burn styled captions into a video with ffmpeg's libass ``ass`` filter.

This is a *final pass* over an already-rendered video: the MoviePy pipeline
stays untouched, and one fast ffmpeg run draws the captions. Word timestamps
must therefore be expressed on the timeline of the video being burned (for a
project render that means remapping source-time words past the cuts first).
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg
from moviepy import VideoFileClip

from backend.features.captions.ass_builder import build_ass
from backend.features.captions.layout import group_words
from backend.features.captions.styles import FONTS_DIR, get_style


def _escape_filter_path(path: str | Path) -> str:
    """Escape a path for use as an ffmpeg filter option value.

    ffmpeg filter parsing treats these characters specially (option and filter
    separators, escapes); a leading backslash makes them literal. Mirrors the
    escaping ffmpeg-python applies to filter arguments.
    """
    escaped = str(path)
    for char in ("\\", "'", ":", "=", ",", ";", "[", "]"):
        escaped = escaped.replace(char, f"\\{char}")
    return escaped


def _video_dimensions(video_path: str | Path) -> tuple[int, int]:
    """Return the display ``(width, height)`` of a video."""
    clip = VideoFileClip(str(video_path))
    try:
        return int(clip.w), int(clip.h)
    finally:
        clip.close()


def video_duration(video_path: str | Path) -> float:
    """Return a video's duration in seconds."""
    clip = VideoFileClip(str(video_path))
    try:
        return float(clip.duration)
    finally:
        clip.close()


def burn_captions(
    video_path: str | Path,
    ass_path: str | Path,
    output_path: str | Path,
    fonts_dir: str | Path | None = FONTS_DIR,
) -> None:
    """Render an ASS subtitle file onto a video.

    Args:
        video_path: Video to draw the captions onto.
        ass_path: Path to the ASS document.
        output_path: Where to write the captioned video (audio is copied
            through untouched).
        fonts_dir: Directory of font files for libass to match against;
            defaults to the bundled caption fonts. ``None`` uses only
            system fonts.

    Raises:
        FileNotFoundError: If ``video_path`` or ``ass_path`` does not exist.
        RuntimeError: If ffmpeg exits with an error.
    """
    for required in (video_path, ass_path):
        if not Path(required).exists():
            raise FileNotFoundError(f"File not found: {required}")

    filter_arg = f"ass=filename={_escape_filter_path(ass_path)}"
    if fonts_dir is not None:
        filter_arg += f":fontsdir={_escape_filter_path(fonts_dir)}"

    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-y",
        "-i",
        str(video_path),
        "-vf",
        filter_arg,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        str(output_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg caption burn failed (exit {result.returncode}): "
            f"{result.stderr[-2000:]}"
        )


def add_captions(
    video_path: str | Path,
    words: list[dict],
    output_path: str | Path,
    style: str = "bold-pop",
    max_words_per_line: int | None = None,
) -> None:
    """Burn shorts-style captions for ``words`` into a video.

    Groups the words into caption pages, builds an ASS document in the chosen
    preset sized to the video's frame, and burns it in.

    Args:
        video_path: Video to caption; ``words`` timestamps must be on this
            video's timeline.
        words: Word entries ``{"start", "end", "word"}`` in time order.
        output_path: Where to write the captioned video.
        style: Preset name from
            :data:`~backend.features.captions.styles.STYLE_PRESETS`.
        max_words_per_line: Words shown at once; defaults to the preset's own
            setting.

    Raises:
        ValueError: If the style is unknown or ``words`` has no usable text.
        RuntimeError: If ffmpeg fails.
    """
    caption_style = get_style(style)
    pages = group_words(
        words, max_words=max_words_per_line or caption_style.max_words_per_line
    )
    if not pages:
        raise ValueError("No caption words to render")

    document = build_ass(pages, caption_style, _video_dimensions(video_path))
    with tempfile.TemporaryDirectory() as tmp_dir:
        ass_path = Path(tmp_dir) / "captions.ass"
        ass_path.write_text(document, encoding="utf-8")
        burn_captions(video_path, ass_path, output_path)
