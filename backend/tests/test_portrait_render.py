"""Tests that rendering preserves portrait orientation (no landscape output).

Portrait sources come in two flavors: physically portrait frames, and
phone-style files that store landscape frames plus rotation side data. Both
must render to a physically portrait output — never a landscape video with
the content squeezed or letterboxed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import imageio_ffmpeg
import pytest
from moviepy import VideoFileClip

from backend.features.video_cutter.cut import render_timeline, render_with_edits

PORTRAIT_SIZE = (180, 320)


def _encode_portrait_fixture(path: Path) -> None:
    """Encode a tiny 2s portrait (180x320) test video."""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    command = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration=2:rate=30:size={PORTRAIT_SIZE[0]}x{PORTRAIT_SIZE[1]}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    subprocess.run(command, check=True, capture_output=True, timeout=120)


def _encode_rotated_fixture(path: Path) -> None:
    """Encode a phone-style portrait: landscape frames + rotation-90 metadata."""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    landscape = path.with_name("landscape_source.mp4")
    command = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration=2:rate=30:size={PORTRAIT_SIZE[1]}x{PORTRAIT_SIZE[0]}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(landscape),
    ]
    subprocess.run(command, check=True, capture_output=True, timeout=120)
    remux = [
        ffmpeg,
        "-y",
        "-display_rotation",
        "90",
        "-i",
        str(landscape),
        "-c",
        "copy",
        str(path),
    ]
    subprocess.run(remux, check=True, capture_output=True, timeout=120)


def _video_size(path: Path) -> tuple[int, int]:
    clip = VideoFileClip(str(path))
    try:
        return tuple(clip.size)
    finally:
        clip.close()


def test_render_with_edits_keeps_portrait_dimensions(tmp_path):
    source = tmp_path / "portrait.mp4"
    _encode_portrait_fixture(source)
    output = tmp_path / "rendered.mp4"

    render_with_edits(
        str(source),
        cut_ranges=[{"start": 0.5, "end": 1.0}],
        zoom_ranges=[{"start": 1.2, "end": 1.6, "level": 1.2}],
        output_path=str(output),
    )

    assert _video_size(output) == PORTRAIT_SIZE


def test_render_timeline_keeps_portrait_dimensions(tmp_path):
    source = tmp_path / "portrait.mp4"
    _encode_portrait_fixture(source)
    output = tmp_path / "rendered.mp4"

    render_timeline(
        str(source),
        segments=[{"start": 1.0, "end": 2.0}, {"start": 0.0, "end": 0.5}],
        output_path=str(output),
    )

    assert _video_size(output) == PORTRAIT_SIZE


def test_render_applies_rotation_metadata_as_portrait(tmp_path):
    source = tmp_path / "phone_portrait.mp4"
    _encode_rotated_fixture(source)
    if _video_size(source) != PORTRAIT_SIZE:
        pytest.skip("bundled ffmpeg does not support -display_rotation")
    output = tmp_path / "rendered.mp4"

    render_with_edits(
        str(source),
        cut_ranges=[{"start": 0.5, "end": 1.0}],
        zoom_ranges=[],
        output_path=str(output),
    )

    assert _video_size(output) == PORTRAIT_SIZE
