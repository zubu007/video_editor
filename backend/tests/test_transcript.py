import os
import unittest
from unittest.mock import patch, MagicMock
from backend.features.transcript.extract import extract_transcript_as_segments, extract_transcript_as_sentences

class TestTranscript(unittest.TestCase):

    def setUp(self):
        # Create a dummy silent video file for testing
        self.silent_video_path = "tests/test_silent_video.mp4"
        if not os.path.exists(self.silent_video_path):
            os.system("ffmpeg -f lavfi -i color=c=black:s=1280x720:r=30:d=1 -f lavfi -i anullsrc=r=48000:cl=stereo -c:v libx264 -c:a aac -shortest " + self.silent_video_path)

        # Create a dummy video file with speech for testing
        self.speech_video_path = "tests/test_video_with_speech.mp4"
        if not os.path.exists(self.speech_video_path):
            os.system("say -o tests/test_audio.aiff 'Hello world. This is a test.'")
            os.system(f"ffmpeg -f lavfi -i color=c=black:s=1280x720:r=30:d=5 -i tests/test_audio.aiff -c:v libx264 -c:a aac -shortest {self.speech_video_path}")

    @patch('features.transcript.extract.WhisperModel')
    def test_extract_transcript_as_segments_silent_video(self, mock_whisper_model):
        mock_model_instance = MagicMock()
        mock_whisper_model.return_value = mock_model_instance
        mock_model_instance.transcribe.return_value = ([], MagicMock(language="en", language_probability=0.9))

        transcript = extract_transcript_as_segments(self.silent_video_path)
        self.assertEqual(transcript, [])

    @patch('features.transcript.extract.WhisperModel')
    def test_extract_transcript_as_sentences_silent_video(self, mock_whisper_model):
        mock_model_instance = MagicMock()
        mock_whisper_model.return_value = mock_model_instance
        mock_model_instance.transcribe.return_value = ([], MagicMock(language="en", language_probability=0.9))

        transcript = extract_transcript_as_sentences(self.silent_video_path)
        self.assertEqual(transcript, [])

    @patch('features.transcript.extract.WhisperModel')
    def test_extract_transcript_as_sentences_with_speech(self, mock_whisper_model):
        mock_model_instance = MagicMock()
        mock_whisper_model.return_value = mock_model_instance

        # Mock word objects
        word1 = MagicMock(word="Hello ", start=0.0, end=0.5)
        word2 = MagicMock(word="world.", start=0.5, end=1.0)
        word3 = MagicMock(word="This ", start=1.5, end=2.0)
        word4 = MagicMock(word="is ", start=2.0, end=2.2)
        word5 = MagicMock(word="a ", start=2.2, end=2.4)
        word6 = MagicMock(word="test.", start=2.4, end=3.0)

        # Mock segment objects
        segment1 = MagicMock(words=[word1, word2])
        segment2 = MagicMock(words=[word3, word4, word5, word6])

        mock_model_instance.transcribe.return_value = ([segment1, segment2], MagicMock(language="en", language_probability=0.9))

        transcript = extract_transcript_as_sentences(self.speech_video_path)
        
        expected_transcript = [
            {'start': 0.0, 'end': 1.0, 'text': 'Hello world.'},
            {'start': 1.5, 'end': 3.0, 'text': 'This is a test.'}
        ]
        
        # A more complex assert to check the structure and content
        self.assertEqual(len(transcript), len(expected_transcript))
        for i, sentence in enumerate(transcript):
            self.assertIn('start', sentence)
            self.assertIn('end', sentence)
            self.assertIn('text', sentence)
            self.assertEqual(sentence['text'], expected_transcript[i]['text'])


    def tearDown(self):
        if os.path.exists(self.silent_video_path):
            os.remove(self.silent_video_path)
        if os.path.exists(self.speech_video_path):
            os.remove(self.speech_video_path)
        if os.path.exists("tests/test_audio.aiff"):
            os.remove("tests/test_audio.aiff")
        if os.path.exists("tests/test_video.mp4"):
            os.remove("tests/test_video.mp4")

if __name__ == '__main__':
    unittest.main()
