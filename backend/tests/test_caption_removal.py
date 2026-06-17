import subprocess
import unittest
from unittest import mock

from backend.features.caption_removal import jobs, remove


class TestBuildCommand(unittest.TestCase):
    def test_builds_cpu_command_with_defaults(self):
        with mock.patch.dict(
            "os.environ",
            {
                "SUBTITLE_REMOVER_DIR": "/tmp/vsr",
                "SUBTITLE_REMOVER_PYTHON": "/tmp/vsr/.venv/bin/python",
            },
            clear=False,
        ):
            command = remove.build_command("in.mp4", "out.mp4")

        self.assertEqual(
            command,
            [
                "/tmp/vsr/.venv/bin/python",
                "-m",
                "backend.processor",
                "-i",
                "in.mp4",
                "-o",
                "out.mp4",
                "-m",
                "sttn",
                "--gpu",
                "-1",
            ],
        )

    def test_use_gpu_sets_device_zero(self):
        command = remove.build_command("in.mp4", "out.mp4", use_gpu=True)
        gpu_index = command.index("--gpu")
        self.assertEqual(command[gpu_index + 1], "0")

    def test_extra_args_appended(self):
        command = remove.build_command(
            "in.mp4", "out.mp4", extra_args=["--no-audio"]
        )
        self.assertEqual(command[-1], "--no-audio")

    def test_invalid_mode_raises_value_error(self):
        with self.assertRaises(ValueError):
            remove.build_command("in.mp4", "out.mp4", mode="bogus")


class TestUseGpuFromEnv(unittest.TestCase):
    def test_truthy_values_enable_gpu(self):
        for value in ["1", "true", "TRUE", "yes", "On"]:
            with mock.patch.dict(
                "os.environ", {"SUBTITLE_REMOVER_USE_GPU": value}, clear=False
            ):
                self.assertTrue(remove.use_gpu_from_env(), value)

    def test_unset_or_falsey_defaults_to_cpu(self):
        for value in ["", "0", "false", "no"]:
            with mock.patch.dict(
                "os.environ", {"SUBTITLE_REMOVER_USE_GPU": value}, clear=False
            ):
                self.assertFalse(remove.use_gpu_from_env(), value)


class TestRemoveCaptions(unittest.TestCase):
    def test_missing_directory_raises_file_not_found(self):
        with mock.patch.object(remove, "get_remover_dir") as get_dir:
            fake_dir = mock.Mock()
            fake_dir.exists.return_value = False
            get_dir.return_value = fake_dir
            with self.assertRaises(FileNotFoundError):
                remove.remove_captions("in.mp4", "out.mp4")

    def test_nonzero_exit_raises_runtime_error(self):
        fake_dir = mock.Mock()
        fake_dir.exists.return_value = True
        completed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="boom failure detail"
        )
        with mock.patch.object(remove, "get_remover_dir", return_value=fake_dir), \
            mock.patch.object(
                remove, "get_remover_python", return_value="/usr/bin/python"
            ), \
            mock.patch(
                "backend.features.caption_removal.remove.Path"
            ) as path_cls, \
            mock.patch(
                "backend.features.caption_removal.remove.subprocess.run",
                return_value=completed,
            ) as run:
            path_cls.return_value.exists.return_value = True
            with self.assertRaises(RuntimeError) as ctx:
                remove.remove_captions("in.mp4", "out.mp4")

        self.assertIn("boom failure detail", str(ctx.exception))
        run.assert_called_once()

    def test_success_invokes_subprocess(self):
        fake_dir = mock.Mock()
        fake_dir.exists.return_value = True
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="ok", stderr=""
        )
        with mock.patch.object(remove, "get_remover_dir", return_value=fake_dir), \
            mock.patch.object(
                remove, "get_remover_python", return_value="/usr/bin/python"
            ), \
            mock.patch(
                "backend.features.caption_removal.remove.Path"
            ) as path_cls, \
            mock.patch(
                "backend.features.caption_removal.remove.subprocess.run",
                return_value=completed,
            ) as run:
            path_cls.return_value.exists.return_value = True
            remove.remove_captions("in.mp4", "out.mp4")

        run.assert_called_once()


class TestJobs(unittest.TestCase):
    def test_create_and_get_job(self):
        job = jobs.create_job("file-123", "nosub_file-123_abcd1234.mp4")
        self.assertEqual(job.status, "pending")
        fetched = jobs.get_job(job.job_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.file_id, "file-123")

    def test_get_unknown_job_returns_none(self):
        self.assertIsNone(jobs.get_job("does-not-exist"))

    def test_run_job_marks_done_on_success(self):
        job = jobs.create_job("file-ok", "out.mp4")
        with mock.patch.object(jobs, "remove_captions") as remove_fn:
            jobs.run_caption_removal_job(job.job_id, "in.mp4", "out.mp4")
            remove_fn.assert_called_once()
        self.assertEqual(jobs.get_job(job.job_id).status, "done")

    def test_run_job_marks_error_on_failure(self):
        job = jobs.create_job("file-bad", "out.mp4")
        with mock.patch.object(
            jobs, "remove_captions", side_effect=RuntimeError("nope")
        ):
            jobs.run_caption_removal_job(job.job_id, "in.mp4", "out.mp4")
        failed = jobs.get_job(job.job_id)
        self.assertEqual(failed.status, "error")
        self.assertEqual(failed.error, "nope")


if __name__ == "__main__":
    unittest.main()
