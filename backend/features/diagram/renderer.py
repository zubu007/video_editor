"""Renders validated diagram specs to video via Manim in a subprocess.

Manim is invoked as an isolated CLI subprocess (its import configures global
state and pulls heavy dependencies into the server process otherwise). The
scene template lives in ``backend/features/diagram/manim_scenes.py`` and reads
the spec from a JSON file, so the LLM output never becomes code.

Two output flavors:

- **preview** (``transparent=False``): an H.264 ``.mp4`` on a dark background,
  playable in the browser's diagram-tab player.
- **overlay** (``transparent=True``): a ``.mov`` with an alpha channel, meant
  to be composited over the source video at final render.

Rendered files are cached in the output directory keyed by a hash of the spec,
so unchanged diagrams are never re-rendered.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

SCENE_FILE = Path(__file__).parent / "manim_scenes.py"
SCENE_NAME = "DiagramScene"

QUALITY_FLAGS = {"low": "l", "medium": "m", "high": "h"}
RENDER_TIMEOUT_SECONDS = 600


def manim_available() -> bool:
    """Returns whether the ``manim`` package is importable."""
    return importlib.util.find_spec("manim") is not None


def spec_cache_key(spec: dict, transparent: bool, quality: str) -> str:
    """Returns a stable hash for a spec + render settings combination."""
    payload = json.dumps(
        {"spec": spec, "transparent": transparent, "quality": quality},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def render_diagram_video(
    spec: dict,
    output_path: str | Path,
    transparent: bool = False,
    quality: str = "low",
) -> Path:
    """Renders one diagram spec to ``output_path`` with Manim.

    Args:
        spec: Validated spec with "diagram_type", "title", "duration" and
            "graph" keys (see ``manim_scenes`` for the exact shape).
        output_path: Where to write the rendered video. The extension should
            be ``.mov`` for transparent renders, ``.mp4`` otherwise.
        transparent: Render with an alpha channel for compositing.
        quality: One of "low", "medium", "high" (Manim quality presets).

    Returns:
        Path: ``output_path`` as a Path.

    Raises:
        RuntimeError: If Manim is not installed or the render fails.
        ValueError: If ``quality`` is unknown.
    """
    if quality not in QUALITY_FLAGS:
        raise ValueError(
            f"Unknown quality {quality!r}; use one of {sorted(QUALITY_FLAGS)}"
        )
    if not manim_available():
        raise RuntimeError(
            "Manim is not installed in the server environment. "
            "Install it with `uv pip install manim` to enable diagram rendering."
        )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="diagram_render_") as workdir:
        workdir_path = Path(workdir)
        spec_path = workdir_path / "spec.json"
        spec_path.write_text(
            json.dumps({**spec, "transparent": transparent}), encoding="utf-8"
        )

        output_name = "diagram_render"
        command = [
            sys.executable,
            "-m",
            "manim",
            "render",
            "--quality",
            QUALITY_FLAGS[quality],
            "--format",
            "mov" if transparent else "mp4",
            "--media_dir",
            str(workdir_path / "media"),
            "--output_file",
            output_name,
        ]
        if transparent:
            command.append("--transparent")
        command.extend([str(SCENE_FILE), SCENE_NAME])

        env = {**os.environ, "DIAGRAM_SPEC_PATH": str(spec_path)}
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            env=env,
            timeout=RENDER_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            tail = (result.stderr or result.stdout or "").strip()[-2000:]
            raise RuntimeError(
                f"Manim render failed (exit {result.returncode}): {tail}"
            )

        extension = ".mov" if transparent else ".mp4"
        rendered = list((workdir_path / "media").rglob(f"{output_name}{extension}"))
        if not rendered:
            raise RuntimeError("Manim reported success but produced no output file")
        rendered[0].replace(output_path)

    return output_path


def get_or_render_overlay(
    spec: dict,
    output_dir: str | Path,
    transparent: bool = False,
    quality: str = "low",
) -> tuple[Path, bool]:
    """Returns the rendered video for ``spec``, rendering only on cache miss.

    Args:
        spec: Validated diagram spec.
        output_dir: Directory where rendered diagram videos are cached.
        transparent: Render with an alpha channel for compositing.
        quality: Manim quality preset ("low", "medium", "high").

    Returns:
        tuple[Path, bool]: The video path and whether it came from the cache.
    """
    key = spec_cache_key(spec, transparent, quality)
    extension = ".mov" if transparent else ".mp4"
    output_path = Path(output_dir) / f"diagram_{key}{extension}"
    if output_path.exists():
        logger.info("Diagram overlay cache hit: %s", output_path.name)
        return output_path, True

    logger.info("Rendering diagram overlay %s (quality=%s)", output_path.name, quality)
    render_diagram_video(spec, output_path, transparent=transparent, quality=quality)
    return output_path, False
