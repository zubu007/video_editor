"""Wrap the external VideoSubtitleRemover CLI to erase burned-in captions.

The third-party tool (https://github.com/SysAdminDoc/VideoSubtitleRemover) ships its
own package named ``backend`` and pulls heavy GPU dependencies, so it is **not** imported
into this project. Instead it is cloned into ``third_party/`` with its own virtualenv and
invoked as an isolated subprocess via its CLI (``python -m backend.processor``).

Configuration is read from two environment variables:

- ``SUBTITLE_REMOVER_DIR``: path to the cloned repository (the ``cwd`` for the subprocess).
- ``SUBTITLE_REMOVER_PYTHON``: path to the python interpreter of that repo's virtualenv.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Inpainting modes accepted by the external CLI's ``-m/--mode`` flag.
MODE_CHOICES = ["sttn", "lama", "propainter", "auto", "migan"]
DEFAULT_MODE = "sttn"

DEFAULT_REMOVER_DIR = "third_party/VideoSubtitleRemover"
# stderr can be huge; only the tail is propagated in error messages.
_STDERR_TAIL_CHARS = 2000


def get_remover_dir() -> Path:
    """Return the configured VideoSubtitleRemover clone directory."""
    return Path(os.environ.get("SUBTITLE_REMOVER_DIR", DEFAULT_REMOVER_DIR))


def get_remover_python() -> str:
    """Return the python interpreter for the tool's virtualenv.

    Defaults to ``<remover_dir>/.venv/bin/python`` when not set explicitly.
    """
    configured = os.environ.get("SUBTITLE_REMOVER_PYTHON")
    if configured:
        return configured
    return str(get_remover_dir() / ".venv" / "bin" / "python")


def use_gpu_from_env() -> bool:
    """Return whether GPU execution is enabled via ``SUBTITLE_REMOVER_USE_GPU``.

    Truthy values are ``1``, ``true``, ``yes``, ``on`` (case-insensitive). Defaults to
    ``False`` (CPU) so machines without a supported NVIDIA GPU work out of the box.
    """
    return os.environ.get("SUBTITLE_REMOVER_USE_GPU", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def build_command(
    video_path: str,
    output_path: str,
    *,
    mode: str = DEFAULT_MODE,
    use_gpu: bool = False,
    extra_args: list[str] | None = None,
) -> list[str]:
    """Build the subprocess command for the external CLI.

    Args:
        video_path: Path to the source video.
        output_path: Path where the cleaned video should be written.
        mode: Inpainting mode (one of ``MODE_CHOICES``).
        use_gpu: When ``False``, pass ``--gpu -1`` to force CPU execution.
        extra_args: Optional additional CLI arguments appended verbatim.

    Returns:
        The command as a list of arguments suitable for :func:`subprocess.run`.

    Raises:
        ValueError: If ``mode`` is not a recognized inpainting mode.
    """
    if mode not in MODE_CHOICES:
        raise ValueError(
            f"Unknown caption removal mode: {mode!r}. Choose from {MODE_CHOICES}."
        )

    command = [
        get_remover_python(),
        "-m",
        "backend.processor",
        "-i",
        video_path,
        "-o",
        output_path,
        "-m",
        mode,
        "--gpu",
        "0" if use_gpu else "-1",
    ]
    if extra_args:
        command.extend(extra_args)
    return command


def remove_captions(
    video_path: str,
    output_path: str,
    *,
    mode: str = DEFAULT_MODE,
    use_gpu: bool = False,
    extra_args: list[str] | None = None,
) -> None:
    """Remove burned-in captions from a video using the external tool.

    Args:
        video_path: Path to the source video.
        output_path: Path where the cleaned video should be written.
        mode: Inpainting mode (one of ``MODE_CHOICES``). Defaults to ``"sttn"``.
        use_gpu: Whether to allow GPU execution. Defaults to CPU-only.
        extra_args: Optional additional CLI arguments appended verbatim.

    Raises:
        ValueError: If ``mode`` is invalid.
        FileNotFoundError: If the configured tool directory or interpreter is missing.
        RuntimeError: If the subprocess exits with a non-zero status.
    """
    remover_dir = get_remover_dir()
    if not remover_dir.exists():
        raise FileNotFoundError(
            f"VideoSubtitleRemover directory not found at {remover_dir}. "
            "Set SUBTITLE_REMOVER_DIR or clone the repo (see CLAUDE.md)."
        )

    remover_python = get_remover_python()
    if not Path(remover_python).exists():
        raise FileNotFoundError(
            f"VideoSubtitleRemover python interpreter not found at {remover_python}. "
            "Set SUBTITLE_REMOVER_PYTHON or create the tool's virtualenv (see CLAUDE.md)."
        )

    command = build_command(
        video_path,
        output_path,
        mode=mode,
        use_gpu=use_gpu,
        extra_args=extra_args,
    )

    result = subprocess.run(
        command,
        cwd=str(remover_dir),
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        stderr_tail = (result.stderr or "").strip()[-_STDERR_TAIL_CHARS:]
        raise RuntimeError(
            f"Caption removal failed (exit code {result.returncode}): {stderr_tail}"
        )
