import unittest
from pathlib import Path
from unittest import mock

from backend.features.youtube import download, jobs


class TestValidateSingleVideo(unittest.TestCase):
    def test_accepts_single_video(self):
        # Should not raise.
        download._validate_single_video({"duration": 600, "title": "ok"})

    def test_rejects_playlist_via_type(self):
        with self.assertRaises(ValueError):
            download._validate_single_video({"_type": "playlist"})

    def test_rejects_playlist_via_entries(self):
        with self.assertRaises(ValueError):
            download._validate_single_video({"entries": [{"id": "a"}]})

    def test_rejects_livestream(self):
        with self.assertRaises(ValueError):
            download._validate_single_video({"is_live": True})

    def test_rejects_upcoming_livestream(self):
        with self.assertRaises(ValueError):
            download._validate_single_video({"live_status": "is_upcoming"})

    def test_rejects_over_long_video(self):
        with self.assertRaises(ValueError):
            download._validate_single_video(
                {"duration": download.MAX_DURATION_SECONDS + 1}
            )

    def test_missing_duration_is_allowed(self):
        download._validate_single_video({"title": "no duration"})


class TestProgressHook(unittest.TestCase):
    def test_reports_fraction_while_downloading(self):
        seen = []
        hook = download._make_progress_hook(seen.append)
        hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
        self.assertEqual(seen, [0.5])

    def test_uses_estimate_when_total_unknown(self):
        seen = []
        hook = download._make_progress_hook(seen.append)
        hook(
            {
                "status": "downloading",
                "downloaded_bytes": 25,
                "total_bytes_estimate": 100,
            }
        )
        self.assertEqual(seen, [0.25])

    def test_ignores_non_downloading_status(self):
        seen = []
        hook = download._make_progress_hook(seen.append)
        hook({"status": "finished"})
        self.assertEqual(seen, [])


class TestJobRegistry(unittest.TestCase):
    def test_create_and_get_job(self):
        job = jobs.create_job("https://youtu.be/abc")
        fetched = jobs.get_job(job.job_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.url, "https://youtu.be/abc")
        self.assertEqual(fetched.status, "pending")
        self.assertEqual(fetched.progress, 0.0)

    def test_get_unknown_job_returns_none(self):
        self.assertIsNone(jobs.get_job("does-not-exist"))

    def test_run_download_job_success(self):
        job = jobs.create_job("https://youtu.be/abc")
        result = {"path": Path("/tmp/x.mp4"), "title": "Clip", "duration": 12.0}
        with (
            mock.patch.object(jobs, "download_video", return_value=result) as dl,
            mock.patch.object(
                jobs, "_persist_media_asset", return_value=("proj-1", "asset-1")
            ) as persist,
        ):
            jobs.run_download_job(
                job.job_id, "https://youtu.be/abc", "file-1", "/tmp/uploads"
            )

        dl.assert_called_once()
        persist.assert_called_once()
        done = jobs.get_job(job.job_id)
        self.assertEqual(done.status, "done")
        self.assertEqual(done.progress, 1.0)
        self.assertEqual(done.file_id, "file-1")
        self.assertEqual(done.project_id, "proj-1")
        self.assertEqual(done.media_asset_id, "asset-1")

    def test_run_download_job_records_download_error(self):
        job = jobs.create_job("https://youtu.be/bad")
        with mock.patch.object(
            jobs,
            "download_video",
            side_effect=ValueError("Playlists are not supported"),
        ):
            jobs.run_download_job(
                job.job_id, "https://youtu.be/bad", "file-2", "/tmp/uploads"
            )

        failed = jobs.get_job(job.job_id)
        self.assertEqual(failed.status, "error")
        self.assertIn("Playlists", failed.error)
        self.assertIsNone(failed.media_asset_id)


if __name__ == "__main__":
    unittest.main()
