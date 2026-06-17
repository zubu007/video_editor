"""Detect NVIDIA GPUs available on the host via ``nvidia-smi``.

This is a best-effort probe used by the frontend Settings panel to tell the user whether
turning on GPU acceleration (for caption removal) is viable. It deliberately relies on
``nvidia-smi`` rather than importing a CUDA-enabled framework: the main backend may ship a
CPU-only ``torch`` while the external caption-removal tool keeps its own GPU virtualenv, so
the presence of the NVIDIA driver is the most reliable cross-process signal.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Optional, TypedDict

from backend.features.caption_removal.remove import get_remover_python

# Fields queried from nvidia-smi, in order, as a CSV with no header/units.
_QUERY_FIELDS = "name,memory.total"
_NVIDIA_SMI_TIMEOUT_SECONDS = 5

# Importing torch + initializing CUDA in a cold venv can take a few seconds.
_TOOL_PROBE_TIMEOUT_SECONDS = 60
# Marker prefix so we can pick our JSON line out of any torch import noise on stdout.
_PROBE_MARKER = "TOOL_CUDA_JSON="
_TOOL_CUDA_PROBE = (
    "import json\n"
    "info = {'available': False, 'device_name': None, 'torch_version': None,"
    " 'error': None}\n"
    "try:\n"
    "    import torch\n"
    "    info['torch_version'] = torch.__version__\n"
    "    info['available'] = bool(torch.cuda.is_available())\n"
    "    if info['available']:\n"
    "        info['device_name'] = torch.cuda.get_device_name(0)\n"
    "except Exception as exc:\n"
    "    info['error'] = type(exc).__name__ + ': ' + str(exc)\n"
    f"print('{_PROBE_MARKER}' + json.dumps(info))\n"
)


class GpuInfo(TypedDict):
    """A single detected GPU."""

    name: str
    memory_total_mb: int | None


class GpuDetection(TypedDict):
    """Result of probing the host for NVIDIA GPUs."""

    available: bool
    gpus: list[GpuInfo]
    detail: str


class ToolCudaDetection(TypedDict):
    """Whether the caption-removal tool's own venv can actually use CUDA.

    ``checked`` is ``False`` when the probe could not run at all (interpreter missing,
    timeout, etc.); ``available`` reflects ``torch.cuda.is_available()`` inside that venv.
    """

    checked: bool
    available: bool
    device_name: Optional[str]
    detail: str


def _parse_line(line: str) -> GpuInfo:
    """Parse one ``name, memory`` CSV line from nvidia-smi."""
    parts = [part.strip() for part in line.split(",")]
    name = parts[0] if parts else "Unknown GPU"
    memory_total_mb: int | None = None
    if len(parts) > 1:
        try:
            memory_total_mb = int(parts[1])
        except ValueError:
            memory_total_mb = None
    return {"name": name, "memory_total_mb": memory_total_mb}


def detect_gpus() -> GpuDetection:
    """Probe the host for NVIDIA GPUs.

    Returns:
        A :class:`GpuDetection` dict. ``available`` is ``True`` only when at least one GPU
        is reported. Never raises — failures (missing ``nvidia-smi``, no driver, timeout)
        are reported via ``available=False`` and a human-readable ``detail``.
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                f"--query-gpu={_QUERY_FIELDS}",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=_NVIDIA_SMI_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return {
            "available": False,
            "gpus": [],
            "detail": "nvidia-smi not found — no NVIDIA driver/GPU on this host.",
        }
    except subprocess.TimeoutExpired:
        return {
            "available": False,
            "gpus": [],
            "detail": "nvidia-smi timed out.",
        }

    if result.returncode != 0:
        detail = (result.stderr or "").strip() or "nvidia-smi returned an error."
        return {"available": False, "gpus": [], "detail": detail}

    gpus = [
        _parse_line(line) for line in result.stdout.splitlines() if line.strip()
    ]
    if not gpus:
        return {
            "available": False,
            "gpus": [],
            "detail": "No NVIDIA GPU detected.",
        }

    return {
        "available": True,
        "gpus": gpus,
        "detail": f"Detected {len(gpus)} NVIDIA GPU(s).",
    }


def _unchecked(detail: str) -> ToolCudaDetection:
    """Build a 'could not probe' result."""
    return {
        "checked": False,
        "available": False,
        "device_name": None,
        "detail": detail,
    }


def detect_tool_cuda() -> ToolCudaDetection:
    """Probe whether the caption-removal tool's venv has a CUDA-capable PyTorch.

    Runs ``torch.cuda.is_available()`` inside ``SUBTITLE_REMOVER_PYTHON`` so the result
    reflects what the actual inpainting subprocess will see — not the main backend's torch.
    Never raises; failures are reported via ``checked=False``.
    """
    python = get_remover_python()
    if not os.path.exists(python):
        return _unchecked(
            f"Tool interpreter not found at {python}. "
            "Complete the GPU setup (see README) to enable GPU acceleration."
        )

    try:
        result = subprocess.run(
            [python, "-c", _TOOL_CUDA_PROBE],
            capture_output=True,
            text=True,
            check=False,
            timeout=_TOOL_PROBE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return _unchecked(f"Could not run the tool interpreter at {python}.")
    except subprocess.TimeoutExpired:
        return _unchecked("Timed out probing the tool's PyTorch/CUDA.")

    marker_line = next(
        (
            line
            for line in result.stdout.splitlines()
            if line.startswith(_PROBE_MARKER)
        ),
        None,
    )
    if marker_line is None:
        detail = (result.stderr or "").strip() or "Could not read the CUDA probe output."
        return _unchecked(detail[:500])

    try:
        info = json.loads(marker_line[len(_PROBE_MARKER) :])
    except json.JSONDecodeError:
        return _unchecked("Could not parse the CUDA probe output.")

    if info.get("error"):
        # torch missing or failed to import in the tool venv.
        return {
            "checked": True,
            "available": False,
            "device_name": None,
            "detail": f"PyTorch unavailable in the tool venv: {info['error']}",
        }

    available = bool(info.get("available"))
    device_name = info.get("device_name")
    torch_version = info.get("torch_version")
    if available:
        detail = f"Tool venv can use the GPU (torch {torch_version})."
    else:
        detail = (
            f"Tool venv has PyTorch {torch_version} but no CUDA device — "
            "install GPU-enabled PyTorch (see README)."
        )
    return {
        "checked": True,
        "available": available,
        "device_name": device_name,
        "detail": detail,
    }
