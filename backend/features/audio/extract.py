"""Audio extraction and waveform generation from video files.

This module provides functionality to:
1. Extract audio from video files as WAV format
2. Generate waveform data optimized for frontend visualization
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TypedDict

import numpy as np
from moviepy import VideoFileClip

logger = logging.getLogger(__name__)


class WaveformData(TypedDict):
    """Type definition for waveform data response."""

    waveform: list[float]
    duration: float
    sample_rate: int
    num_samples: int


def extract_audio_as_wav(video_path: str, output_path: str) -> str:
    """
    Extract audio from video and save as WAV file.

    Args:
        video_path: Path to input video file
        output_path: Path where WAV file should be saved

    Returns:
        Path to the created WAV file

    Raises:
        Exception: If audio extraction fails
    """
    logger.info(f"Extracting audio from {video_path} to {output_path}")

    video = None
    try:
        video = VideoFileClip(video_path)

        if video.audio is None:
            raise ValueError("Video file has no audio track")

        # Export audio as WAV with 44.1kHz sample rate, 16-bit PCM
        video.audio.write_audiofile(
            output_path,
            codec="pcm_s16le",
            fps=44100,
            nbytes=2,
            logger=None,  # Suppress moviepy's verbose output
        )

        logger.info(f"Audio extraction completed: {output_path}")
        return output_path

    finally:
        if video is not None:
            video.close()


def get_waveform_data(video_path: str, num_samples: int = 2000) -> WaveformData:
    """
    Generate waveform data from video for visualization.

    Extracts audio from the video and generates downsampled amplitude data
    optimized for frontend waveform visualization. The waveform represents
    peak amplitudes across the audio duration.

    Args:
        video_path: Path to input video file
        num_samples: Number of waveform samples to generate (default: 2000)
                    Higher values = more detail but larger response size

    Returns:
        Dictionary containing:
            - waveform: List of peak amplitude values (0.0 to 1.0)
            - duration: Audio duration in seconds
            - sample_rate: Audio sample rate in Hz
            - num_samples: Number of samples in waveform array

    Raises:
        ValueError: If video has no audio track
        Exception: If waveform generation fails
    """
    logger.info(f"Generating waveform data from {video_path} ({num_samples} samples)")

    video = None
    try:
        video = VideoFileClip(video_path)

        if video.audio is None:
            raise ValueError("Video file has no audio track")

        audio = video.audio
        duration = audio.duration

        # Get audio as numpy array (shape: [samples] or [samples, channels])
        # fps parameter sets the sample rate
        audio_array = audio.to_soundarray(fps=44100)

        # Convert stereo to mono by averaging channels
        if len(audio_array.shape) > 1 and audio_array.shape[1] > 1:
            audio_array = audio_array.mean(axis=1)
        elif len(audio_array.shape) > 1:
            # Single channel, squeeze to 1D
            audio_array = audio_array.squeeze()

        # Calculate how many audio samples per waveform pixel
        total_audio_samples = len(audio_array)
        samples_per_pixel = max(1, total_audio_samples // num_samples)

        # Generate waveform by finding peak amplitude in each chunk
        waveform = []
        for i in range(num_samples):
            start = i * samples_per_pixel
            end = min(start + samples_per_pixel, total_audio_samples)

            if start < total_audio_samples:
                chunk = audio_array[start:end]
                # Get peak amplitude for this chunk (absolute value)
                peak = float(np.abs(chunk).max()) if len(chunk) > 0 else 0.0
                waveform.append(peak)
            else:
                # Pad with zeros if we've run out of audio data
                waveform.append(0.0)

        logger.info(f"Waveform generation completed: {len(waveform)} samples")

        return WaveformData(
            waveform=waveform,
            duration=duration,
            sample_rate=44100,
            num_samples=len(waveform),
        )

    finally:
        if video is not None:
            video.close()


def get_waveform_data_from_file_id(
    file_id: str, upload_dir: Path, num_samples: int = 2000
) -> WaveformData:
    """
    Generate waveform data from a file ID.

    Convenience function that looks up the video file by ID and generates waveform data.

    Args:
        file_id: Unique file identifier
        upload_dir: Directory where uploaded files are stored
        num_samples: Number of waveform samples to generate

    Returns:
        Waveform data dictionary

    Raises:
        FileNotFoundError: If video file not found
    """
    # Find the video file (check common extensions)
    video_path = None
    for ext in [".mp4", ".webm", ".mov", ".avi", ".mkv"]:
        candidate = upload_dir / f"{file_id}{ext}"
        if candidate.exists():
            video_path = candidate
            break

    if not video_path:
        raise FileNotFoundError(f"Video file not found for ID: {file_id}")

    return get_waveform_data(str(video_path), num_samples)
