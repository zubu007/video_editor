import os
import unittest
from backend.features.video_cutter.cut import cut_filler_words
from moviepy.editor import VideoFileClip

class TestVideoCutter(unittest.TestCase):

    def setUp(self):
        self.video_path = "tests/test_video_for_cutting.mp4"
        self.output_path = "tests/test_video_for_cutting_edited.mp4"
        if not os.path.exists(self.video_path):
            os.system(f"ffmpeg -f lavfi -i color=c=black:s=1280x720:r=30:d=10 -f lavfi -i anullsrc=r=48000:cl=stereo -c:v libx264 -c:a aac -shortest {self.video_path}")

    def test_cut_filler_words(self):
        filler_word_ranges = [
            {'start': 1, 'end': 2},
            {'start': 5, 'end': 6},
            {'start': 8, 'end': 9},
        ]

        # Get original duration
        original_duration = VideoFileClip(self.video_path).duration

        # Cut the video
        cut_filler_words(self.video_path, filler_word_ranges, self.output_path)

        # Check that the output file exists
        self.assertTrue(os.path.exists(self.output_path))

        # Check the duration of the edited video
        edited_duration = VideoFileClip(self.output_path).duration
        expected_duration = original_duration - 3  # 3 seconds of filler words
        self.assertAlmostEqual(edited_duration, expected_duration, delta=0.5)

    def tearDown(self):
        if os.path.exists(self.video_path):
            os.remove(self.video_path)
        if os.path.exists(self.output_path):
            os.remove(self.output_path)

if __name__ == '__main__':
    unittest.main()
