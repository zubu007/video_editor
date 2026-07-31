import subprocess
import unittest
from unittest.mock import patch

from backend.features.gaming.highlight_jobs import (
    create_job,
    get_job,
    run_highlight_job,
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


if __name__ == "__main__":
    unittest.main()
