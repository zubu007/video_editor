"""Pydantic schema for the ``.vedit`` project file document."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

# Magic string identifying our project files; validated on load.
PROJECT_FILE_FORMAT = "video-editor-project"
# Bump when the document shape changes in a non-backward-compatible way.
PROJECT_FILE_VERSION = 1

# Conventional extension for saved project files.
PROJECT_FILE_EXTENSION = ".vedit"


class FileFingerprint(BaseModel):
    """A cheap signature used to detect whether a referenced file has changed."""

    size: Optional[int] = Field(None, description="File size in bytes")
    mtime: Optional[float] = Field(None, description="Last-modified time (epoch seconds)")


class MediaRef(BaseModel):
    """A reference to a source media file, by path rather than embedded."""

    file_id: str = Field(..., description="Original uploaded file identifier")
    filename: str = Field(..., description="Original display filename")
    extension: str = Field(..., description="On-disk file extension, e.g. '.mp4'")
    duration: Optional[float] = None
    size: Optional[int] = None
    path_abs: Optional[str] = Field(None, description="Absolute path at save time")
    path_rel: Optional[str] = Field(
        None, description="Path relative to the app working directory at save time"
    )
    fingerprint: FileFingerprint = Field(default_factory=FileFingerprint)


class StockRef(BaseModel):
    """A reference to a downloaded stock-footage clip."""

    filename: str
    path_abs: Optional[str] = None
    path_rel: Optional[str] = None
    source: str = "pexels"
    query: Optional[str] = None
    provider_id: Optional[str] = None
    duration: Optional[float] = None
    size: Optional[int] = None
    fingerprint: FileFingerprint = Field(default_factory=FileFingerprint)


class EditRef(BaseModel):
    """A single non-destructive edit operation."""

    type: str = "cut"
    source: str = "silence_detection"
    start: float
    end: float
    enabled: bool = True
    media_file_id: Optional[str] = Field(
        None, description="file_id of the media this edit applies to"
    )
    details: dict[str, Any] = Field(default_factory=dict)


class PlanRef(BaseModel):
    """The saved AI editing plan and the options used to generate it."""

    plan: list[Any] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)
    media_file_id: Optional[str] = None


class ProjectMeta(BaseModel):
    """Project-level metadata."""

    id: str
    name: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ProjectFile(BaseModel):
    """The full ``.vedit`` document."""

    format: str = Field(PROJECT_FILE_FORMAT, description="Magic format identifier")
    version: int = Field(PROJECT_FILE_VERSION, description="Document schema version")
    saved_at: Optional[datetime] = None
    source_project_id: Optional[str] = Field(
        None, description="Project id this file was exported from"
    )
    project: ProjectMeta
    media: list[MediaRef] = Field(default_factory=list)
    stock_footage: list[StockRef] = Field(default_factory=list)
    edits: list[EditRef] = Field(default_factory=list)
    editing_plan: Optional[PlanRef] = None
    options: dict[str, Any] = Field(default_factory=dict)
    transcript_cache: dict[str, Any] = Field(default_factory=dict)
