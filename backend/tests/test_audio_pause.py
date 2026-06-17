import unittest
import os
import tempfile
import wave

import numpy as np

from backend.features.audio_pause.detect import (
    detect_audio_pauses,
    detect_audio_pauses_from_wav,
    filter_pauses_by_duration,
    get_total_silence_duration,
    merge_nearby_pauses,
)


class TestAudioPauseDetection(unittest.TestCase):

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test files."""
        import shutil

        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def create_test_wav_with_silence(
        self, duration_seconds: float = 10.0, silence_segments: list = None
    ) -> str:
        """
        Creates a test WAV file with specified silence segments.

        Args:
            duration_seconds (float): Total duration of the audio file.
            silence_segments (list): List of (start, end) tuples for silence in seconds.

        Returns:
            str: Path to the created WAV file.
        """
        sample_rate = 44100
        num_samples = int(duration_seconds * sample_rate)

        # Create audio data (sine wave at 440 Hz)
        t = np.linspace(0, duration_seconds, num_samples)
        audio_data = np.sin(2 * np.pi * 440 * t) * 0.3  # Moderate volume

        # Apply silence to specified segments
        if silence_segments:
            for start, end in silence_segments:
                start_sample = int(start * sample_rate)
                end_sample = int(end * sample_rate)
                audio_data[start_sample:end_sample] = 0.0

        # Convert to 16-bit PCM
        audio_data_int16 = (audio_data * 32767).astype(np.int16)

        # Create WAV file
        wav_path = os.path.join(self.test_dir, "test_audio.wav")
        with wave.open(wav_path, "w") as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(audio_data_int16.tobytes())

        return wav_path

    def test_detect_audio_pauses_from_wav_basic(self):
        """Test basic silence detection from WAV file."""
        # Create a test WAV with silence from 2.0s to 4.0s
        wav_path = self.create_test_wav_with_silence(
            duration_seconds=10.0, silence_segments=[(2.0, 4.0)]
        )

        # Detect pauses
        pauses = detect_audio_pauses_from_wav(
            wav_path,
            min_silence_duration=1.0,
            silence_threshold=-50,  # Very low threshold for complete silence
        )

        # Should detect one pause
        self.assertGreater(len(pauses), 0)

        # Check that the detected pause is around 2.0-4.0s
        # (allowing some tolerance for detection)
        pause = pauses[0]
        self.assertAlmostEqual(pause["start"], 2.0, delta=0.5)
        self.assertAlmostEqual(pause["end"], 4.0, delta=0.5)
        self.assertAlmostEqual(pause["duration"], 2.0, delta=0.5)

    def test_detect_multiple_pauses(self):
        """Test detecting multiple silence segments."""
        # Create a test WAV with multiple silence segments
        wav_path = self.create_test_wav_with_silence(
            duration_seconds=20.0,
            silence_segments=[(2.0, 4.0), (8.0, 10.0), (15.0, 18.0)],
        )

        pauses = detect_audio_pauses_from_wav(
            wav_path, min_silence_duration=1.0, silence_threshold=-50
        )

        # Should detect three pauses
        self.assertGreaterEqual(len(pauses), 3)

    def test_min_silence_duration_filter(self):
        """Test that minimum silence duration is respected."""
        # Create short silence (0.5s) and long silence (2.0s)
        wav_path = self.create_test_wav_with_silence(
            duration_seconds=10.0, silence_segments=[(2.0, 2.5), (5.0, 7.0)]
        )

        # Detect with 1.0s minimum
        pauses = detect_audio_pauses_from_wav(
            wav_path, min_silence_duration=1.0, silence_threshold=-50
        )

        # Should only detect the longer pause
        for pause in pauses:
            self.assertGreaterEqual(pause["duration"], 0.9)  # Allow small tolerance

    def test_filter_pauses_by_duration(self):
        """Test filtering pauses by duration."""
        pauses = [
            {"start": 0.0, "end": 1.5, "duration": 1.5},
            {"start": 5.0, "end": 8.0, "duration": 3.0},
            {"start": 10.0, "end": 11.0, "duration": 1.0},
            {"start": 15.0, "end": 20.0, "duration": 5.0},
        ]

        # Filter by minimum duration
        filtered = filter_pauses_by_duration(pauses, min_duration=2.0)
        self.assertEqual(len(filtered), 2)
        for pause in filtered:
            self.assertGreaterEqual(pause["duration"], 2.0)

        # Filter by maximum duration
        filtered = filter_pauses_by_duration(pauses, max_duration=3.0)
        self.assertEqual(len(filtered), 3)
        for pause in filtered:
            self.assertLessEqual(pause["duration"], 3.0)

        # Filter by range
        filtered = filter_pauses_by_duration(pauses, min_duration=1.5, max_duration=3.0)
        self.assertEqual(len(filtered), 2)

    def test_get_total_silence_duration(self):
        """Test calculating total silence duration."""
        pauses = [
            {"start": 0.0, "end": 2.0, "duration": 2.0},
            {"start": 5.0, "end": 8.0, "duration": 3.0},
            {"start": 10.0, "end": 11.5, "duration": 1.5},
        ]

        total = get_total_silence_duration(pauses)
        self.assertEqual(total, 6.5)

    def test_merge_nearby_pauses(self):
        """Test merging nearby pause segments."""
        pauses = [
            {"start": 0.0, "end": 2.0, "duration": 2.0},
            {"start": 2.3, "end": 4.0, "duration": 1.7},  # Close to previous
            {"start": 10.0, "end": 12.0, "duration": 2.0},  # Far away
        ]

        # Merge with 0.5s max gap
        merged = merge_nearby_pauses(pauses, max_gap=0.5)

        # Should merge first two pauses
        self.assertEqual(len(merged), 2)
        self.assertAlmostEqual(merged[0]["start"], 0.0)
        self.assertAlmostEqual(merged[0]["end"], 4.0)
        self.assertAlmostEqual(merged[1]["start"], 10.0)

    def test_merge_nearby_pauses_no_merge(self):
        """Test that distant pauses are not merged."""
        pauses = [
            {"start": 0.0, "end": 2.0, "duration": 2.0},
            {"start": 5.0, "end": 7.0, "duration": 2.0},
        ]

        merged = merge_nearby_pauses(pauses, max_gap=0.5)

        # Should not merge
        self.assertEqual(len(merged), 2)

    def test_detect_audio_pauses_file_not_found(self):
        """Test error handling for non-existent video file."""
        # This now tests the centralized audio extraction error handling
        with self.assertRaises((FileNotFoundError, ValueError)):
            detect_audio_pauses("/nonexistent/video.mp4")

    def test_pause_structure(self):
        """Test that pause dictionaries have the correct structure."""
        wav_path = self.create_test_wav_with_silence(
            duration_seconds=10.0, silence_segments=[(2.0, 4.0)]
        )

        pauses = detect_audio_pauses_from_wav(wav_path, min_silence_duration=1.0)

        for pause in pauses:
            self.assertIn("start", pause)
            self.assertIn("end", pause)
            self.assertIn("duration", pause)
            self.assertIsInstance(pause["start"], float)
            self.assertIsInstance(pause["end"], float)
            self.assertIsInstance(pause["duration"], float)
            self.assertGreaterEqual(pause["end"], pause["start"])
            self.assertAlmostEqual(pause["duration"], pause["end"] - pause["start"])


if __name__ == "__main__":
    unittest.main()
