import json
import subprocess
import unittest
from unittest import mock

from backend.features.system import gpu


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


class TestDetectGpus(unittest.TestCase):
    def test_parses_detected_gpus(self):
        stdout = "NVIDIA GeForce RTX 5060, 8192\nNVIDIA RTX A2000, 6144\n"
        with mock.patch.object(
            gpu.subprocess, "run", return_value=_completed(stdout=stdout)
        ):
            result = gpu.detect_gpus()

        self.assertTrue(result["available"])
        self.assertEqual(len(result["gpus"]), 2)
        self.assertEqual(result["gpus"][0]["name"], "NVIDIA GeForce RTX 5060")
        self.assertEqual(result["gpus"][0]["memory_total_mb"], 8192)

    def test_missing_nvidia_smi_returns_unavailable(self):
        with mock.patch.object(
            gpu.subprocess, "run", side_effect=FileNotFoundError()
        ):
            result = gpu.detect_gpus()

        self.assertFalse(result["available"])
        self.assertEqual(result["gpus"], [])
        self.assertIn("nvidia-smi", result["detail"])

    def test_timeout_returns_unavailable(self):
        with mock.patch.object(
            gpu.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=5),
        ):
            result = gpu.detect_gpus()

        self.assertFalse(result["available"])
        self.assertIn("timed out", result["detail"])

    def test_nonzero_exit_returns_unavailable(self):
        with mock.patch.object(
            gpu.subprocess,
            "run",
            return_value=_completed(returncode=9, stderr="driver error"),
        ):
            result = gpu.detect_gpus()

        self.assertFalse(result["available"])
        self.assertIn("driver error", result["detail"])

    def test_empty_output_returns_unavailable(self):
        with mock.patch.object(
            gpu.subprocess, "run", return_value=_completed(stdout="\n")
        ):
            result = gpu.detect_gpus()

        self.assertFalse(result["available"])

    def test_missing_memory_field_is_tolerated(self):
        with mock.patch.object(
            gpu.subprocess, "run", return_value=_completed(stdout="Some GPU")
        ):
            result = gpu.detect_gpus()

        self.assertTrue(result["available"])
        self.assertIsNone(result["gpus"][0]["memory_total_mb"])


class TestDetectToolCuda(unittest.TestCase):
    def _probe_stdout(self, **info):
        return gpu._PROBE_MARKER + json.dumps(info) + "\n"

    def test_interpreter_missing_is_unchecked(self):
        with mock.patch.object(
            gpu, "get_remover_python", return_value="/no/such/python"
        ), mock.patch.object(gpu.os.path, "exists", return_value=False):
            result = gpu.detect_tool_cuda()

        self.assertFalse(result["checked"])
        self.assertFalse(result["available"])
        self.assertIn("not found", result["detail"])

    def test_cuda_available_reports_device(self):
        stdout = self._probe_stdout(
            available=True,
            device_name="NVIDIA GeForce RTX 5060",
            torch_version="2.10.0+cu128",
            error=None,
        )
        with mock.patch.object(
            gpu, "get_remover_python", return_value="/venv/python"
        ), mock.patch.object(gpu.os.path, "exists", return_value=True), mock.patch.object(
            gpu.subprocess, "run", return_value=_completed(stdout=stdout)
        ):
            result = gpu.detect_tool_cuda()

        self.assertTrue(result["checked"])
        self.assertTrue(result["available"])
        self.assertEqual(result["device_name"], "NVIDIA GeForce RTX 5060")

    def test_torch_present_but_no_cuda(self):
        stdout = self._probe_stdout(
            available=False, device_name=None, torch_version="2.10.0", error=None
        )
        with mock.patch.object(
            gpu, "get_remover_python", return_value="/venv/python"
        ), mock.patch.object(gpu.os.path, "exists", return_value=True), mock.patch.object(
            gpu.subprocess, "run", return_value=_completed(stdout=stdout)
        ):
            result = gpu.detect_tool_cuda()

        self.assertTrue(result["checked"])
        self.assertFalse(result["available"])
        self.assertIn("no CUDA device", result["detail"])

    def test_torch_import_error_is_checked_but_unavailable(self):
        stdout = self._probe_stdout(
            available=False,
            device_name=None,
            torch_version=None,
            error="ModuleNotFoundError: No module named 'torch'",
        )
        with mock.patch.object(
            gpu, "get_remover_python", return_value="/venv/python"
        ), mock.patch.object(gpu.os.path, "exists", return_value=True), mock.patch.object(
            gpu.subprocess, "run", return_value=_completed(stdout=stdout)
        ):
            result = gpu.detect_tool_cuda()

        self.assertTrue(result["checked"])
        self.assertFalse(result["available"])
        self.assertIn("PyTorch unavailable", result["detail"])

    def test_no_marker_line_is_unchecked(self):
        with mock.patch.object(
            gpu, "get_remover_python", return_value="/venv/python"
        ), mock.patch.object(gpu.os.path, "exists", return_value=True), mock.patch.object(
            gpu.subprocess,
            "run",
            return_value=_completed(stdout="random noise", stderr="boom"),
        ):
            result = gpu.detect_tool_cuda()

        self.assertFalse(result["checked"])
        self.assertIn("boom", result["detail"])

    def test_timeout_is_unchecked(self):
        with mock.patch.object(
            gpu, "get_remover_python", return_value="/venv/python"
        ), mock.patch.object(gpu.os.path, "exists", return_value=True), mock.patch.object(
            gpu.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="python", timeout=60),
        ):
            result = gpu.detect_tool_cuda()

        self.assertFalse(result["checked"])
        self.assertIn("Timed out", result["detail"])


if __name__ == "__main__":
    unittest.main()
