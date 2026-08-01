import subprocess
import unittest
from unittest.mock import patch

from backend.features.gaming.highlight_jobs import (
    caption_words_for_clip,
    create_job,
    get_job,
    run_highlight_job,
    text_captions_for_clip,
)


class TestHighlightJobs(unittest.TestCase):
    def test_run_highlight_job_records_output(self):
        job = create_job("file-abc")
        self.assertEqual(job.status, "pending")

        with patch("backend.features.gaming.highlight_jobs.subprocess.run") as mock_run:
            run_highlight_job(
                job.job_id,
                "/tmp/source.mp4",
                10.0,
                25.0,
                "/tmp/out/highlight.mp4",
                "highlight.mp4",
            )
            mock_run.assert_called_once()

        done = get_job(job.job_id)
        self.assertEqual(done.status, "done")
        self.assertEqual(done.filename, "highlight.mp4")
        self.assertEqual(done.output_url, "/api/renders/highlight.mp4")
        self.assertEqual(done.duration, 15.0)
        self.assertIsNone(done.error)

    def test_run_highlight_job_square_adds_the_reframe_graph(self):
        job = create_job("file-square")

        with (
            patch(
                "backend.features.gaming.reel_crop.video_dimensions",
                return_value=(1920, 1080),
            ),
            patch("backend.features.gaming.highlight_jobs.subprocess.run") as mock_run,
        ):
            run_highlight_job(
                job.job_id,
                "/tmp/source.mp4",
                0.0,
                8.0,
                "/tmp/out/reel.mp4",
                "reel.mp4",
                square=True,
            )

        command = mock_run.call_args[0][0]
        self.assertIn("-filter_complex", command)
        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("crop=1080:1080:420:0", graph)
        # The reframed video is mapped explicitly, and audio is carried over.
        self.assertIn("[reel_out]", command)
        self.assertIn("0:a?", command)
        self.assertEqual(get_job(job.job_id).status, "done")

    def test_run_highlight_job_without_square_has_no_filter(self):
        job = create_job("file-wide")

        with patch("backend.features.gaming.highlight_jobs.subprocess.run") as mock_run:
            run_highlight_job(
                job.job_id, "/tmp/source.mp4", 0.0, 4.0, "/tmp/out/w.mp4", "w.mp4"
            )

        self.assertNotIn("-filter_complex", mock_run.call_args[0][0])

    def test_run_highlight_job_reports_an_unusable_source(self):
        job = create_job("file-portrait")

        with (
            patch(
                "backend.features.gaming.reel_crop.video_dimensions",
                return_value=(1080, 1920),
            ),
            patch("backend.features.gaming.highlight_jobs.subprocess.run") as mock_run,
        ):
            run_highlight_job(
                job.job_id,
                "/tmp/source.mp4",
                0.0,
                4.0,
                "/tmp/out/reel.mp4",
                "reel.mp4",
                square=True,
            )
            mock_run.assert_not_called()

        failed = get_job(job.job_id)
        self.assertEqual(failed.status, "error")
        self.assertIn("landscape", failed.error)

    def test_run_highlight_job_burns_overlapping_captions(self):
        job = create_job("file-cap")
        captions_edits = [
            {
                "start": 0.0,
                "end": 100.0,
                "details": {
                    "style": "karaoke",
                    "max_words_per_line": 3,
                    "words": [
                        {"start": 5.0, "end": 5.4, "word": "before"},
                        {"start": 12.0, "end": 12.5, "word": "inside"},
                    ],
                },
            }
        ]
        text_caption_edits = [
            {"start": 14.0, "end": 18.0, "details": {"text": "nice play"}}
        ]

        with (
            patch("backend.features.gaming.highlight_jobs.subprocess.run") as mock_run,
            patch("backend.features.gaming.highlight_jobs.add_captions") as mock_words,
            patch(
                "backend.features.gaming.highlight_jobs.add_text_captions"
            ) as mock_notes,
        ):
            run_highlight_job(
                job.job_id,
                "/tmp/source.mp4",
                10.0,
                25.0,
                "/tmp/out/highlight.mp4",
                "highlight.mp4",
                captions_edits=captions_edits,
                text_caption_edits=text_caption_edits,
            )

        # The trim writes an intermediate, then the two burn passes chain to
        # the final path: transcript captions first, text notes on top.
        trim_target = mock_run.call_args[0][0][-1]
        self.assertEqual(trim_target, "/tmp/out/precaption_highlight.mp4")

        (source, words, out), kwargs = mock_words.call_args
        self.assertEqual(str(source), "/tmp/out/precaption_highlight.mp4")
        self.assertEqual(str(out), "/tmp/out/pretext_highlight.mp4")
        self.assertEqual(words, [{"start": 2.0, "end": 2.5, "word": "inside"}])
        self.assertEqual(kwargs["style"], "karaoke")
        self.assertEqual(kwargs["max_words_per_line"], 3)

        source, notes, out = mock_notes.call_args[0]
        self.assertEqual(str(source), "/tmp/out/pretext_highlight.mp4")
        self.assertEqual(str(out), "/tmp/out/highlight.mp4")
        self.assertEqual(notes[0]["start"], 4.0)
        self.assertEqual(notes[0]["end"], 8.0)
        self.assertEqual(notes[0]["text"], "nice play")

        self.assertEqual(get_job(job.job_id).status, "done")

    def test_run_highlight_job_skips_captions_outside_the_clip(self):
        job = create_job("file-nocap")
        captions_edits = [
            {
                "start": 0.0,
                "end": 5.0,
                "details": {"words": [{"start": 1.0, "end": 1.5, "word": "early"}]},
            }
        ]

        with (
            patch("backend.features.gaming.highlight_jobs.subprocess.run") as mock_run,
            patch("backend.features.gaming.highlight_jobs.add_captions") as mock_words,
        ):
            run_highlight_job(
                job.job_id,
                "/tmp/source.mp4",
                10.0,
                25.0,
                "/tmp/out/plain.mp4",
                "plain.mp4",
                captions_edits=captions_edits,
            )

        # Nothing survives the clip window, so no burn pass and no intermediate.
        mock_words.assert_not_called()
        self.assertEqual(mock_run.call_args[0][0][-1], "/tmp/out/plain.mp4")
        self.assertEqual(get_job(job.job_id).status, "done")

    def test_run_highlight_job_records_ffmpeg_error(self):
        job = create_job("file-def")

        with patch(
            "backend.features.gaming.highlight_jobs.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "ffmpeg", stderr="boom"),
        ):
            run_highlight_job(
                job.job_id,
                "/tmp/source.mp4",
                0.0,
                5.0,
                "/tmp/out/clip.mp4",
                "clip.mp4",
            )

        failed = get_job(job.job_id)
        self.assertEqual(failed.status, "error")
        self.assertEqual(failed.error, "Failed to create highlight clip")
        self.assertIsNone(failed.filename)


class TestCaptionClipRemap(unittest.TestCase):
    def test_caption_words_for_clip_filters_and_shifts(self):
        words = [
            {"start": 8.0, "end": 8.5, "word": "before"},
            {"start": 9.8, "end": 10.4, "word": "straddles"},
            {"start": 12.0, "end": 12.5, "word": "inside"},
            {"start": 16.0, "end": 16.5, "word": "uncovered"},
            {"start": 24.8, "end": 25.4, "word": "after"},
        ]
        # Captions edits cover 0-15s only; the clip is 10-25s.
        clipped = caption_words_for_clip(words, [(0.0, 15.0)], 10.0, 25.0)

        self.assertEqual([w["word"] for w in clipped], ["straddles", "inside"])
        # A word straddling the clip start is clamped to 0 on the clip timeline.
        self.assertEqual(clipped[0]["start"], 0.0)
        self.assertAlmostEqual(clipped[0]["end"], 0.4)
        self.assertEqual(clipped[1]["start"], 2.0)
        self.assertEqual(clipped[1]["end"], 2.5)

    def test_text_captions_for_clip_clamps_and_drops(self):
        edits = [
            {"start": 2.0, "end": 6.0, "details": {"text": "too early"}},
            {
                "start": 12.0,
                "end": 30.0,
                "details": {"text": "gg", "position": "top", "reveal_seconds": 1.5},
            },
            {"start": 13.0, "end": 14.0, "details": {"text": "   "}},
        ]
        captions = text_captions_for_clip(edits, 10.0, 25.0)

        self.assertEqual(len(captions), 1)
        self.assertEqual(captions[0]["text"], "gg")
        self.assertEqual(captions[0]["start"], 2.0)
        # The span is clamped to the clip's duration.
        self.assertEqual(captions[0]["end"], 15.0)
        self.assertEqual(captions[0]["position"], "top")
        self.assertEqual(captions[0]["reveal_seconds"], 1.5)


if __name__ == "__main__":
    unittest.main()
