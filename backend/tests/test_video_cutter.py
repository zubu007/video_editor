import subprocess
import tempfile
import unittest
from pathlib import Path

from backend.features.video_cutter.cut import (
    _RenderProgressLogger,
    cut_filler_words,
    render_timeline,
    render_with_edits,
)
from moviepy import VideoFileClip, concatenate_videoclips


class TestVideoCutter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        test_dir = Path(self.temp_dir.name)
        self.video_path = test_dir / "test_video_for_cutting.mp4"
        self.output_path = test_dir / "test_video_for_cutting_edited.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=1280x720:r=30:d=10",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=48000:cl=stereo",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-shortest",
                str(self.video_path),
            ],
            check=True,
        )

    def test_cut_filler_words(self):
        filler_word_ranges = [
            {"start": 1, "end": 2},
            {"start": 5, "end": 6},
            {"start": 8, "end": 9},
        ]

        # Get original duration
        original_duration = VideoFileClip(str(self.video_path)).duration

        # Cut the video
        cut_filler_words(
            str(self.video_path), filler_word_ranges, str(self.output_path)
        )

        # Check that the output file exists
        self.assertTrue(self.output_path.exists())

        # Check the duration of the edited video
        edited_duration = VideoFileClip(str(self.output_path)).duration
        expected_duration = original_duration - 3  # 3 seconds of filler words
        self.assertAlmostEqual(edited_duration, expected_duration, delta=0.5)

    def test_render_with_zoom_preserves_dimensions_and_duration(self):
        original = VideoFileClip(str(self.video_path))
        original_duration = original.duration
        original_size = (original.w, original.h)

        # Zoom into the middle of the clip, no cuts.
        render_with_edits(
            str(self.video_path),
            [],
            [{"start": 3, "end": 6, "level": 1.5}],
            str(self.output_path),
        )

        self.assertTrue(self.output_path.exists())
        rendered = VideoFileClip(str(self.output_path))
        # A pure zoom must not change the timeline or the frame size.
        self.assertAlmostEqual(rendered.duration, original_duration, delta=0.5)
        self.assertEqual((rendered.w, rendered.h), original_size)

    def test_render_with_cut_and_zoom(self):
        original_duration = VideoFileClip(str(self.video_path)).duration

        render_with_edits(
            str(self.video_path),
            [{"start": 1, "end": 2}],
            [{"start": 4, "end": 7, "level": 1.3}],
            str(self.output_path),
        )

        self.assertTrue(self.output_path.exists())
        edited_duration = VideoFileClip(str(self.output_path)).duration
        # One second removed; the zoom does not affect duration.
        self.assertAlmostEqual(edited_duration, original_duration - 1, delta=0.5)

    def _make_clip(self, path: Path, color: str, duration: int = 4) -> None:
        """Render a solid-color silent test clip with ffmpeg."""
        subprocess.run(
            [
                "ffmpeg",
                "-f", "lavfi",
                "-i", f"color=c={color}:s=640x360:r=30:d={duration}",
                "-c:v", "libx264",
                str(path),
            ],
            check=True,
        )

    def test_render_with_stock_footage_overlays_broll(self):
        original = VideoFileClip(str(self.video_path))
        original_duration = original.duration
        original_size = (original.w, original.h)

        stock_path = Path(self.temp_dir.name) / "stock_red.mp4"
        self._make_clip(stock_path, "red")

        # Overlay the (red) B-roll over a span of the (black) source.
        render_with_edits(
            str(self.video_path),
            [],
            [],
            str(self.output_path),
            [{"start": 3, "end": 6, "footage_path": str(stock_path)}],
        )

        self.assertTrue(self.output_path.exists())
        rendered = VideoFileClip(str(self.output_path))
        # An overlay must not change the timeline or the frame size.
        self.assertAlmostEqual(rendered.duration, original_duration, delta=0.5)
        self.assertEqual((rendered.w, rendered.h), original_size)
        # The overlaid span should show the red B-roll, not the black source.
        overlaid = rendered.get_frame(4.5)
        self.assertGreater(int(overlaid[..., 0].mean()), 100)
        # Outside the overlay the source stays black.
        source = rendered.get_frame(1.0)
        self.assertLess(int(source.mean()), 40)

    def test_render_with_still_image_overlays_broll(self):
        original = VideoFileClip(str(self.video_path))
        original_duration = original.duration
        original_size = (original.w, original.h)

        image_path = Path(self.temp_dir.name) / "stock_red.png"
        subprocess.run(
            [
                "ffmpeg",
                "-f", "lavfi",
                "-i", "color=c=red:s=640x360",
                "-frames:v", "1",
                str(image_path),
            ],
            check=True,
        )

        # Hold the (red) still image over a span of the (black) source.
        render_with_edits(
            str(self.video_path),
            [],
            [],
            str(self.output_path),
            [{"start": 3, "end": 6, "footage_path": str(image_path)}],
        )

        self.assertTrue(self.output_path.exists())
        rendered = VideoFileClip(str(self.output_path))
        # A still overlay must not change the timeline or the frame size.
        self.assertAlmostEqual(rendered.duration, original_duration, delta=0.5)
        self.assertEqual((rendered.w, rendered.h), original_size)
        # The overlaid span should show the red image, not the black source.
        overlaid = rendered.get_frame(4.5)
        self.assertGreater(int(overlaid[..., 0].mean()), 100)
        # Outside the overlay the source stays black.
        source = rendered.get_frame(1.0)
        self.assertLess(int(source.mean()), 40)

    def test_render_timeline_reorders_segments(self):
        red = Path(self.temp_dir.name) / "red.mp4"
        blue = Path(self.temp_dir.name) / "blue.mp4"
        self._make_clip(red, "red", 3)
        self._make_clip(blue, "blue", 3)
        source = Path(self.temp_dir.name) / "two_color.mp4"
        concatenate_videoclips(
            [VideoFileClip(str(red)), VideoFileClip(str(blue))]
        ).write_videofile(str(source), codec="libx264")

        # Play the blue half (3-6s) before the red half (0-3s).
        render_timeline(
            str(source),
            [{"start": 3, "end": 6}, {"start": 0, "end": 3}],
            str(self.output_path),
        )

        self.assertTrue(self.output_path.exists())
        rendered = VideoFileClip(str(self.output_path))
        self.assertAlmostEqual(rendered.duration, 6, delta=0.5)
        first = rendered.get_frame(1.0)
        self.assertGreater(int(first[..., 2].mean()), 100)
        self.assertLess(int(first[..., 0].mean()), 80)
        second = rendered.get_frame(4.5)
        self.assertGreater(int(second[..., 0].mean()), 100)
        self.assertLess(int(second[..., 2].mean()), 80)

    def test_render_timeline_subtracts_cuts_within_segments(self):
        # Reordered halves of the 10s source, with one cut in each half.
        render_timeline(
            str(self.video_path),
            [{"start": 5, "end": 10}, {"start": 0, "end": 5}],
            str(self.output_path),
            cut_ranges=[{"start": 1, "end": 2}, {"start": 6, "end": 7}],
        )

        self.assertTrue(self.output_path.exists())
        edited_duration = VideoFileClip(str(self.output_path)).duration
        self.assertAlmostEqual(edited_duration, 8, delta=0.5)

    def test_render_reports_progress_to_callback(self):
        seen = []
        render_with_edits(
            str(self.video_path),
            [{"start": 1, "end": 2}],
            [],
            str(self.output_path),
            on_progress=seen.append,
        )

        self.assertTrue(seen, "expected the encoder to report progress")
        self.assertTrue(all(0.0 <= value <= 1.0 for value in seen))
        self.assertTrue(
            all(b >= a for a, b in zip(seen, seen[1:])),
            "progress should climb monotonically",
        )
        self.assertAlmostEqual(seen[-1], 1.0, delta=0.05)

    def tearDown(self):
        self.temp_dir.cleanup()


class TestRenderProgressLogger(unittest.TestCase):
    """The logger must track MoviePy's video bar and ignore the audio bar.

    MoviePy ticks a ``frame_index`` bar per written video frame (``t`` on 1.x) and a
    separate ``chunk`` bar for the audio pass, which completes *first*. Reporting the
    audio bar too would send the UI's progress back to zero mid-render.
    """

    def _logger(self):
        seen = []
        logger = _RenderProgressLogger(seen.append)
        return logger, seen

    def test_reports_video_bar_as_fraction(self):
        logger, seen = self._logger()
        logger.bars["frame_index"] = {"total": 4}

        for index in range(5):
            logger.bars_callback("frame_index", "index", index)

        self.assertEqual(seen, [0.0, 0.25, 0.5, 0.75, 1.0])

    def test_ignores_audio_chunk_bar(self):
        logger, seen = self._logger()
        logger.bars["chunk"] = {"total": 10}

        logger.bars_callback("chunk", "index", 5)

        self.assertEqual(seen, [])

    def test_ignores_non_index_attributes(self):
        logger, seen = self._logger()
        logger.bars["frame_index"] = {"total": 4}

        logger.bars_callback("frame_index", "total", 4)

        self.assertEqual(seen, [])

    def test_tolerates_missing_total(self):
        logger, seen = self._logger()
        logger.bars["frame_index"] = {}

        logger.bars_callback("frame_index", "index", 3)

        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
