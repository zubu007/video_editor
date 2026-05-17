"""
Audio pause/silence detection from video files.

This module detects segments of silence in video files that exceed
a specified duration threshold.
"""

import os
import tempfile
from typing import List, Optional

from pydub import AudioSegment
from pydub.silence import detect_silence

from backend.features.audio.extract import extract_audio_as_wav


def detect_audio_pauses(
    video_path: str,
    min_silence_duration: float = 1.0,
    silence_threshold: int = -40,
    seek_step: int = 1
) -> List[dict]:
    """
    Detects audio pauses/silence in a video file.

    Args:
        video_path (str): Path to the video file.
        min_silence_duration (float): Minimum duration of silence in seconds to detect.
                                      Default is 1.0 seconds.
        silence_threshold (int): Audio level threshold in dBFS below which audio is
                                considered silent. Default is -40 dBFS.
                                Lower values = stricter silence detection.
        seek_step (int): Step size in milliseconds for scanning audio.
                        Smaller values are more precise but slower. Default is 1ms.

    Returns:
        list: A list of dictionaries with silence segments.
              Each dictionary contains:
              - "start" (float): Start time of silence in seconds
              - "end" (float): End time of silence in seconds
              - "duration" (float): Duration of silence in seconds

    Example:
        >>> pauses = detect_audio_pauses("podcast.mp4", min_silence_duration=2.0)
        >>> print(pauses)
        [
            {"start": 45.2, "end": 47.8, "duration": 2.6},
            {"start": 103.5, "end": 106.0, "duration": 2.5}
        ]
    """
    # Extract audio to temporary WAV file
    temp_audio_path = None
    
    try:
        # Create temporary file for extracted audio
        temp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        temp_audio_path = temp_file.name
        temp_file.close()
        
        # Extract audio from video using centralized extraction
        extract_audio_as_wav(video_path, temp_audio_path)
        
        # Load the audio file
        audio = AudioSegment.from_wav(temp_audio_path)
        
        # Convert min_silence_duration to milliseconds
        min_silence_ms = int(min_silence_duration * 1000)
        
        # Detect silence using pydub
        silence_ranges = detect_silence(
            audio,
            min_silence_len=min_silence_ms,
            silence_thresh=silence_threshold,
            seek_step=seek_step
        )
        
        # Convert to our format with seconds
        pauses = []
        for start_ms, end_ms in silence_ranges:
            start_sec = start_ms / 1000.0
            end_sec = end_ms / 1000.0
            duration_sec = end_sec - start_sec
            
            pauses.append({
                "start": start_sec,
                "end": end_sec,
                "duration": duration_sec
            })
        
        return pauses
        
    finally:
        # Clean up temporary audio file
        if temp_audio_path and os.path.exists(temp_audio_path):
            try:
                os.unlink(temp_audio_path)
            except Exception:
                pass  # Ignore cleanup errors


def detect_audio_pauses_from_wav(
    wav_path: str,
    min_silence_duration: float = 1.0,
    silence_threshold: int = -40,
    seek_step: int = 1
) -> List[dict]:
    """
    Detects audio pauses/silence from a WAV file.

    Args:
        wav_path (str): Path to the WAV file.
        min_silence_duration (float): Minimum duration of silence in seconds to detect.
        silence_threshold (int): Audio level threshold in dBFS below which audio is
                                considered silent. Default is -40 dBFS.
        seek_step (int): Step size in milliseconds for scanning audio.

    Returns:
        list: A list of dictionaries with silence segments.
              Each dictionary contains "start", "end", and "duration" in seconds.
    """
    if not os.path.exists(wav_path):
        raise FileNotFoundError(f"WAV file not found: {wav_path}")
    
    # Load the audio file
    audio = AudioSegment.from_wav(wav_path)
    
    # Convert min_silence_duration to milliseconds
    min_silence_ms = int(min_silence_duration * 1000)
    
    # Detect silence
    silence_ranges = detect_silence(
        audio,
        min_silence_len=min_silence_ms,
        silence_thresh=silence_threshold,
        seek_step=seek_step
    )
    
    # Convert to seconds
    pauses = []
    for start_ms, end_ms in silence_ranges:
        start_sec = start_ms / 1000.0
        end_sec = end_ms / 1000.0
        duration_sec = end_sec - start_sec
        
        pauses.append({
            "start": start_sec,
            "end": end_sec,
            "duration": duration_sec
        })
    
    return pauses


def filter_pauses_by_duration(
    pauses: List[dict],
    min_duration: Optional[float] = None,
    max_duration: Optional[float] = None
) -> List[dict]:
    """
    Filters pause segments by duration.

    Args:
        pauses (list): List of pause dictionaries.
        min_duration (float, optional): Minimum duration in seconds (inclusive).
        max_duration (float, optional): Maximum duration in seconds (inclusive).

    Returns:
        list: Filtered list of pauses.
    """
    filtered = pauses
    
    if min_duration is not None:
        filtered = [p for p in filtered if p['duration'] >= min_duration]
    
    if max_duration is not None:
        filtered = [p for p in filtered if p['duration'] <= max_duration]
    
    return filtered


def get_total_silence_duration(pauses: List[dict]) -> float:
    """
    Calculates the total duration of all silence segments.

    Args:
        pauses (list): List of pause dictionaries.

    Returns:
        float: Total silence duration in seconds.
    """
    return sum(p['duration'] for p in pauses)


def merge_nearby_pauses(pauses: List[dict], max_gap: float = 0.5) -> List[dict]:
    """
    Merges pause segments that are close together.

    Args:
        pauses (list): List of pause dictionaries.
        max_gap (float): Maximum gap in seconds between pauses to merge.
                        Default is 0.5 seconds.

    Returns:
        list: List of merged pause segments.
    """
    if not pauses:
        return []
    
    # Sort by start time
    sorted_pauses = sorted(pauses, key=lambda x: x['start'])
    
    merged = []
    current = sorted_pauses[0].copy()
    
    for pause in sorted_pauses[1:]:
        gap = pause['start'] - current['end']
        
        if gap <= max_gap:
            # Merge with current
            current['end'] = pause['end']
            current['duration'] = current['end'] - current['start']
        else:
            # Save current and start new segment
            merged.append(current)
            current = pause.copy()
    
    # Add the last segment
    merged.append(current)
    
    return merged
