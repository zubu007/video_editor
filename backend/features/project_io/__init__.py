"""Save/load support for portable ``.vedit`` project files.

A ``.vedit`` file is a JSON document that captures a project's full working
state — source media, edits, the editing plan, stock footage and options —
referencing media files *by path* rather than embedding them. Loading a file
re-creates the project and relinks the referenced media if it has not moved.
"""

from __future__ import annotations

from backend.features.project_io.export import build_project_file
from backend.features.project_io.import_ import ImportResult, load_project_file
from backend.features.project_io.schema import (
    PROJECT_FILE_EXTENSION,
    PROJECT_FILE_FORMAT,
    PROJECT_FILE_VERSION,
    ProjectFile,
)

__all__ = [
    "build_project_file",
    "load_project_file",
    "ImportResult",
    "ProjectFile",
    "PROJECT_FILE_EXTENSION",
    "PROJECT_FILE_FORMAT",
    "PROJECT_FILE_VERSION",
]
