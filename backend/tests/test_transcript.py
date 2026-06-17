import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.features.transcript.extract import (
    extract_transcript_as_segments,
    extract_transcript_as_sentences,
)


class TestTranscript(unittest.TestCase):
    def setUp(self):
        test_dir = Path(__file__).parent
        self.silent_video_path = test_dir / "test_silent_video.mp4"
        self.speech_video_path = test_dir / "test_video_with_speech.mp4"
        self.silent_video_path.write_bytes(b"")
        self.speech_video_path.write_bytes(b"")

    @patch("backend.features.transcript.extract.WhisperModel")
    def test_extract_transcript_as_segments_silent_video(self, mock_whisper_model):
        mock_model_instance = MagicMock()
        mock_whisper_model.return_value = mock_model_instance
        mock_model_instance.transcribe.return_value = (
            [],
            MagicMock(language="en", language_probability=0.9),
        )

        transcript = extract_transcript_as_segments(str(self.silent_video_path))
        self.assertEqual(transcript, [])

    @patch("backend.features.transcript.extract.WhisperModel")
    def test_extract_transcript_as_sentences_silent_video(self, mock_whisper_model):
        mock_model_instance = MagicMock()
        mock_whisper_model.return_value = mock_model_instance
        mock_model_instance.transcribe.return_value = (
            [],
            MagicMock(language="en", language_probability=0.9),
        )

        transcript = extract_transcript_as_sentences(str(self.silent_video_path))
        self.assertEqual(transcript, [])

    @patch("backend.features.transcript.extract.WhisperModel")
    def test_extract_transcript_as_sentences_with_speech(self, mock_whisper_model):
        mock_model_instance = MagicMock()
        mock_whisper_model.return_value = mock_model_instance

        word1 = MagicMock(word="Hello ", start=0.0, end=0.5)
        word2 = MagicMock(word="world.", start=0.5, end=1.0)
        word3 = MagicMock(word="This ", start=1.5, end=2.0)
        word4 = MagicMock(word="is ", start=2.0, end=2.2)
        word5 = MagicMock(word="a ", start=2.2, end=2.4)
        word6 = MagicMock(word="test.", start=2.4, end=3.0)

        segment1 = MagicMock(words=[word1, word2])
        segment2 = MagicMock(words=[word3, word4, word5, word6])

        mock_model_instance.transcribe.return_value = (
            [segment1, segment2],
            MagicMock(language="en", language_probability=0.9),
        )

        transcript = extract_transcript_as_sentences(str(self.speech_video_path))

        expected_transcript = [
            {"start": 0.0, "end": 1.0, "text": "Hello world."},
            {"start": 1.5, "end": 3.0, "text": "This is a test."},
        ]

        self.assertEqual(len(transcript), len(expected_transcript))
        for i, sentence in enumerate(transcript):
            self.assertIn("start", sentence)
            self.assertIn("end", sentence)
            self.assertIn("text", sentence)
            self.assertEqual(sentence["text"], expected_transcript[i]["text"])

    def tearDown(self):
        self.silent_video_path.unlink(missing_ok=True)
        self.speech_video_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
