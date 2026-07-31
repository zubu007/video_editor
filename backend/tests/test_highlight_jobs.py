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
