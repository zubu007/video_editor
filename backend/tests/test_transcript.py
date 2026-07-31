import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.features.transcript.extract import (
    extract_transcript_as_segments,
    extract_transcript_as_sentences,
    extract_transcript_as_words,
)
from backend.features.transcript.jobs import (
    create_job,
    get_job,
    run_transcript_job,
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

    @patch("backend.features.transcript.extract.WhisperModel")
    def test_extract_words_reports_progress(self, mock_whisper_model):
        mock_model_instance = MagicMock()
        mock_whisper_model.return_value = mock_model_instance

        word1 = MagicMock(word="Hello ", start=0.0, end=0.5)
        word2 = MagicMock(word="world.", start=0.5, end=1.0)
        word3 = MagicMock(word="Again.", start=1.5, end=2.0)
        segment1 = MagicMock(words=[word1, word2], end=1.0)
        segment2 = MagicMock(words=[word3], end=2.0)

        mock_model_instance.transcribe.return_value = (
            [segment1, segment2],
            MagicMock(language="en", language_probability=0.9, duration=2.0),
        )

        progress = []
        words = extract_transcript_as_words(
            str(self.speech_video_path), on_progress=progress.append
        )

        self.assertEqual(len(words), 3)
        # Progress advances per segment (0.5, 1.0) and finishes at 1.0.
        self.assertEqual(progress[0], 0.5)
        self.assertEqual(progress[-1], 1.0)
        self.assertTrue(all(0.0 <= p <= 1.0 for p in progress))

    def test_run_transcript_job_records_words_and_progress(self):
        job = create_job("file-123", model_size="base")
        self.assertEqual(job.status, "pending")

        with patch(
            "backend.features.transcript.jobs.extract_transcript_as_words"
        ) as mock_extract:

            def fake_extract(video_path, model_size, on_progress=None):
                if on_progress:
                    on_progress(0.5)
                    on_progress(1.0)
                return [{"start": 0.0, "end": 0.5, "word": "Hi "}]

            mock_extract.side_effect = fake_extract
            run_transcript_job(job.job_id, "/tmp/video.mp4", "base")

        done = get_job(job.job_id)
        self.assertEqual(done.status, "done")
        self.assertEqual(done.progress, 1.0)
        self.assertEqual(len(done.words), 1)
        self.assertEqual(done.words[0]["word"], "Hi ")

    def test_run_transcript_job_records_error(self):
        job = create_job("file-456")

        with patch(
            "backend.features.transcript.jobs.extract_transcript_as_words",
            side_effect=RuntimeError("boom"),
        ):
            run_transcript_job(job.job_id, "/tmp/video.mp4", "base")

        failed = get_job(job.job_id)
        self.assertEqual(failed.status, "error")
        self.assertIn("boom", failed.error)

    def tearDown(self):
        self.silent_video_path.unlink(missing_ok=True)
        self.speech_video_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
