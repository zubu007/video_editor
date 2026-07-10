"""Tests for VFR detection and constant-frame-rate normalization."""

from __future__ import annotations

import subprocess
from pathlib import Path

import imageio_ffmpeg

from backend.app import (
    ensure_constant_frame_rate,
    is_variable_frame_rate,
    parse_copy_stats,
    parse_stream_frame_rates,
    probe_frame_rates,
    target_constant_fps,
)

VFR_STREAM_LINE = (
    "Stream #0:1[0x2](und): Video: h264 (Baseline) (avc1 / 0x31637661), "
    "yuv420p(tv, smpte170m/smpte170m/bt709, progressive), 1920x1080, "
    "1384 kb/s, SAR 1:1 DAR 16:9, 16.57 fps, 30 tbr, 30k tbn (default)"
)
CFR_STREAM_LINE = (
    "Stream #0:0[0x1](eng): Video: h264 (High) (avc1 / 0x31637661), "
    "yuv420p(tv, bt709, progressive), 360x640, 676 kb/s, "
    "29.97 fps, 29.97 tbr, 30k tbn (default)"
)


def test_parse_stream_frame_rates_vfr_line():
    assert parse_stream_frame_rates(VFR_STREAM_LINE) == (16.57, 30.0)


def test_parse_stream_frame_rates_cfr_line():
    assert parse_stream_frame_rates(CFR_STREAM_LINE) == (29.97, 29.97)


def test_parse_stream_frame_rates_ignores_tbn():
    average_fps, declared_fps = parse_stream_frame_rates("25 fps, 90k tbn")
    assert average_fps == 25.0
    assert declared_fps is None


def test_parse_stream_frame_rates_kilo_suffix():
    _, declared_fps = parse_stream_frame_rates("25 fps, 1k tbr")
    assert declared_fps == 1000.0


def test_parse_stream_frame_rates_empty():
    assert parse_stream_frame_rates("") == (None, None)


def test_parse_stream_frame_rates_uses_first_video_stream():
    output = VFR_STREAM_LINE + "\n" + CFR_STREAM_LINE
    assert parse_stream_frame_rates(output) == (16.57, 30.0)


def test_parse_copy_stats_reads_last_progress_line():
    output = (
        "frame=  500 fps=0.0 q=-1.0 size=N/A time=00:00:30.00 bitrate=N/A\n"
        "frame= 1529 fps=0.0 q=-1.0 Lsize=N/A time=00:01:32.63 bitrate=N/A "
        "speed=4.96e+03x"
    )
    assert parse_copy_stats(output) == (1529, 92.63)


def test_parse_copy_stats_without_progress_line():
    assert parse_copy_stats("Stream #0:0: Video: h264") == (None, None)


def test_is_variable_frame_rate_detects_mediarecorder_output():
    assert is_variable_frame_rate(16.57, 30.0)


def test_is_variable_frame_rate_tolerates_ntsc_rates():
    assert not is_variable_frame_rate(29.97, 30.0)


def test_is_variable_frame_rate_handles_missing_values():
    assert not is_variable_frame_rate(None, 30.0)
    assert not is_variable_frame_rate(30.0, None)
    assert not is_variable_frame_rate(None, None)


def test_target_constant_fps_uses_declared_rate():
    assert target_constant_fps(30.0) == 30.0
    assert target_constant_fps(29.97) == 29.97


def test_target_constant_fps_falls_back_on_bad_rates():
    assert target_constant_fps(None) == 30.0
    assert target_constant_fps(1000.0) == 30.0
    assert target_constant_fps(2.0) == 30.0


def _encode_fixture(path: Path, *, vfr: bool, extra_args: list[str]) -> None:
    """Encode a tiny 2s test video, optionally with irregular frame timing."""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    command = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=2:rate=30:size=64x64",
    ]
    if vfr:
        # Keep an irregular subset of frames with original timestamps so the
        # measured rate (~18 fps) diverges from the declared 30 tbr, mimicking
        # browser MediaRecorder output.
        command += [
            "-vf",
            "select='not(mod(n,2))+not(mod(n,5))'",
            "-fps_mode",
            "passthrough",
        ]
    command += extra_args + [str(path)]
    subprocess.run(command, check=True, capture_output=True, timeout=120)


def test_probe_and_normalize_vfr_mp4(tmp_path):
    video = tmp_path / "capture.mp4"
    _encode_fixture(
        video, vfr=True, extra_args=["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    )

    average_fps, declared_fps = probe_frame_rates(video)
    assert is_variable_frame_rate(average_fps, declared_fps)

    result = ensure_constant_frame_rate(video)
    assert result == video
    assert video.exists()

    average_fps, declared_fps = probe_frame_rates(video)
    assert not is_variable_frame_rate(average_fps, declared_fps)
    assert declared_fps == 30.0


def test_ensure_constant_frame_rate_leaves_cfr_untouched(tmp_path):
    video = tmp_path / "clean.mp4"
    _encode_fixture(
        video, vfr=False, extra_args=["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    )
    original_bytes = video.stat().st_size

    result = ensure_constant_frame_rate(video)

    assert result == video
    assert video.stat().st_size == original_bytes


def test_ensure_constant_frame_rate_converts_webm_to_mp4(tmp_path):
    video = tmp_path / "capture.webm"
    _encode_fixture(video, vfr=True, extra_args=["-c:v", "libvpx", "-an"])

    result = ensure_constant_frame_rate(video)

    assert result == tmp_path / "capture.mp4"
    assert result.exists()
    assert not video.exists()

    average_fps, declared_fps = probe_frame_rates(result)
    assert not is_variable_frame_rate(average_fps, declared_fps)
