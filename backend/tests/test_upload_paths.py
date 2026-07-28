"""Tests for upload filename sanitizing.

The stateless upload endpoints take a client-supplied ``video.filename`` and
both write to and unlink the resulting path, so a name that escapes
``UPLOAD_DIR`` is an arbitrary-write *and* an arbitrary-delete.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app import (
    OUTPUT_DIR,
    UPLOAD_DIR,
    safe_download_name,
    temp_upload_path,
)

# Names that must never escape their directory.
TRAVERSAL_NAMES = [
    "../../../../tmp/evil",
    "../../etc/passwd",
    "..",
    "../",
    "/etc/passwd",
    "/absolute.mp4",
    "sub/dir/video.mp4",
    "..\\..\\windows\\system32\\evil",
    "....//....//evil.mp4",
]


def _is_inside(path: Path, directory: Path) -> bool:
    """True if ``path`` resolves to a location under ``directory``."""
    return directory.resolve() in path.resolve().parents


@pytest.mark.parametrize("filename", TRAVERSAL_NAMES)
def test_temp_upload_path_contains_traversal(filename):
    path = temp_upload_path(filename)

    assert _is_inside(path, UPLOAD_DIR)
    assert path.parent.resolve() == UPLOAD_DIR.resolve()


def test_temp_upload_path_keeps_a_normal_extension():
    path = temp_upload_path("my holiday video.MP4")

    assert path.suffix == ".mp4"
    assert path.parent.resolve() == UPLOAD_DIR.resolve()


def test_temp_upload_path_drops_the_original_name():
    """The stored name must not carry client-controlled text at all."""
    path = temp_upload_path("payload.mp4")

    assert "payload" not in path.name
    assert path.stem.startswith("upload_")


def test_temp_upload_path_is_collision_free():
    first = temp_upload_path("clip.mp4")
    second = temp_upload_path("clip.mp4")

    assert first != second


@pytest.mark.parametrize(
    "filename",
    ["no_extension", "trailing.", "weird.exe!", "long.extensionthatiswaytoolong"],
)
def test_temp_upload_path_drops_unusable_suffixes(filename):
    path = temp_upload_path(filename)

    assert path.name == path.stem
    assert path.parent.resolve() == UPLOAD_DIR.resolve()


@pytest.mark.parametrize("filename", TRAVERSAL_NAMES)
def test_safe_download_name_is_a_single_segment(filename):
    name = safe_download_name(filename)

    assert "/" not in name
    assert "\\" not in name
    assert not name.startswith(".")
    # The prefixed form the cut endpoint builds must stay inside OUTPUT_DIR.
    assert (OUTPUT_DIR / f"edited_{name}").parent.resolve() == OUTPUT_DIR.resolve()


def test_safe_download_name_keeps_readable_names():
    assert safe_download_name("my_clip-01.mp4") == "my_clip-01.mp4"


def test_safe_download_name_falls_back_when_nothing_survives():
    assert safe_download_name("../..") == "video.mp4"
    assert safe_download_name("", fallback="clip.mp4") == "clip.mp4"
