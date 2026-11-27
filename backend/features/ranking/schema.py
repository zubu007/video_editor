"""Versioned, typed composition document for a ranking short."""

from __future__ import annotations

import re
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SCHEMA_VERSION = 1
CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1920
FPS = 30
DEFAULT_CLIP_COUNT = 5
MIN_CLIPS = 2
MAX_CLIPS = 10
MAX_HEADING_LINES = 3

FontKey = Literal["montserrat", "anton", "bangers"]
Preset = Literal["header_band", "full_frame"]
Align = Literal["left", "center", "right"]
Fit = Literal["fill", "fit"]

HEX_PATTERN = r"^#[0-9a-fA-F]{6}$"


def new_clip_id() -> str:
    """Return a fresh stable clip identifier."""
    return uuid.uuid4().hex[:12]


class Run(BaseModel):
    """A run of heading text sharing one optional accent colour."""

    text: str = Field(..., max_length=200)
    color: str | None = Field(None, pattern=HEX_PATTERN)


class Heading(BaseModel):
    """Heading text and style."""

    runs: list[Run] = Field(default_factory=lambda: [Run(text="Top 5 ranking")])
    font: FontKey = "montserrat"
    size: int = Field(76, ge=24, le=160)
    fill: str = Field("#ffffff", pattern=HEX_PATTERN)
    outline_color: str = Field("#000000", pattern=HEX_PATTERN)
    outline_width: int = Field(6, ge=0, le=20)
    shadow: bool = True
    align: Align = "center"
    y: int = Field(110, ge=0, le=1800, description="Vertical centre of the heading")
    backing_color: str = Field("#000000", pattern=HEX_PATTERN)
    backing_opacity: float = Field(0.0, ge=0, le=1)

    @property
    def text(self) -> str:
        """Return the concatenated plain text."""
        return "".join(run.text for run in self.runs)


class RankingStyle(BaseModel):
    """Ranking column style and geometry."""

    reveal_policy: Literal["on_clip_start_persist"] = "on_clip_start_persist"
    font: FontKey = "montserrat"
    number_size: int = Field(96, ge=48, le=200)
    title_size: int = Field(52, ge=32, le=120)
    number_color: str = Field("#ffffff", pattern=HEX_PATTERN)
    title_color: str = Field("#ffffff", pattern=HEX_PATTERN)
    active_color: str = Field("#ffd400", pattern=HEX_PATTERN)
    number_colors: dict[str, str] = Field(
        default_factory=dict, description="Optional per-rank number colour"
    )
    outline_color: str = Field("#000000", pattern=HEX_PATTERN)
    outline_width: int = Field(5, ge=0, le=20)
    shadow: bool = True
    left: int = Field(48, ge=0, le=600)
    number_width: int = Field(112, ge=48, le=300)
    title_width: int = Field(500, ge=200, le=900)
    top: int = Field(320, ge=0, le=1700)
    bottom: int = Field(1500, ge=200, le=1920)
    title_align: Align = "left"

    @field_validator("number_colors")
    @classmethod
    def _validate_number_colors(cls, value: dict[str, str]) -> dict[str, str]:
        for rank, color in value.items():
            if not rank.isdigit() or not re.match(HEX_PATTERN, color):
                raise ValueError("number_colors must map rank -> #rrggbb")
        return value

    @model_validator(mode="after")
    def _area(self) -> RankingStyle:
        if self.bottom - self.top < 200:
            raise ValueError("Ranking area must be at least 200 px tall")
        return self


class Canvas(BaseModel):
    """Output canvas settings."""

    width: int = CANVAS_WIDTH
    height: int = CANVAS_HEIGHT
    fps: int = FPS
    preset: Preset = "header_band"
    background: str = Field("#101010", pattern=HEX_PATTERN)

    @model_validator(mode="after")
    def _fixed_v1(self) -> Canvas:
        if (self.width, self.height, self.fps) != (CANVAS_WIDTH, CANVAS_HEIGHT, FPS):
            raise ValueError("V1 renders 1080x1920 at 30 fps only")
        return self

    @property
    def viewport(self) -> tuple[int, int, int, int]:
        """Return the footage viewport as ``(x, y, width, height)``."""
        if self.preset == "full_frame":
            return (0, 0, self.width, self.height)
        return (0, 220, self.width, 1520)


class MediaInfo(BaseModel):
    """Probe results for an attached source. Server-owned."""

    duration: float
    width: int
    height: int
    has_audio: bool
    fps: float | None = None


class Clip(BaseModel):
    """One ranking entry."""

    id: str = Field(default_factory=new_clip_id)
    rank: int = Field(..., ge=1)
    playback_order: int = Field(..., ge=1)
    name: str = Field("", max_length=120)
    source_url: str = Field("", max_length=2000)
    provider: str | None = None
    asset_id: str | None = Field(None, description="Server-owned")
    media: MediaInfo | None = Field(None, description="Server-owned")
    source_generation: int = Field(0, ge=0, description="Server-owned")
    trim_in: float = Field(0.0, ge=0)
    trim_out: float | None = Field(None, description="None = to end of source")
    fit: Fit = "fill"
    focal_x: float = Field(0.5, ge=0, le=1)
    focal_y: float = Field(0.5, ge=0, le=1)
    zoom: float = Field(1.0, ge=1.0, le=4.0)
    fit_background: str = Field("#000000", pattern=HEX_PATTERN)
    volume: float = Field(1.0, ge=0, le=2)
    muted: bool = False

    @property
    def resolved_out(self) -> float | None:
        """Return the effective trim-out, or ``None`` if the source is unknown."""
        if self.trim_out is not None:
            return self.trim_out
        return self.media.duration if self.media else None


class ExportSettings(BaseModel):
    """Fixed V1 export settings (recorded for forward compatibility)."""

    container: Literal["mp4"] = "mp4"
    video_codec: Literal["h264"] = "h264"
    audio_codec: Literal["aac"] = "aac"


class RankingDocument(BaseModel):
    """The whole persisted composition."""

    schema_version: int = SCHEMA_VERSION
    revision: int = 1
    project_id: str = ""
    canvas: Canvas = Field(default_factory=Canvas)
    heading: Heading = Field(default_factory=Heading)
    ranking: RankingStyle = Field(default_factory=RankingStyle)
    clips: list[Clip] = Field(default_factory=list)
    export: ExportSettings = Field(default_factory=ExportSettings)

    @model_validator(mode="after")
    def _structure(self) -> RankingDocument:
        count = len(self.clips)
        if not MIN_CLIPS <= count <= MAX_CLIPS:
            raise ValueError(f"A ranking needs {MIN_CLIPS}-{MAX_CLIPS} clips")
        ids = [c.id for c in self.clips]
        if len(set(ids)) != count:
            raise ValueError("Clip ids must be unique")
        if sorted(c.rank for c in self.clips) != list(range(1, count + 1)):
            raise ValueError("Ranks must be unique and contiguous 1..N")
        if sorted(c.playback_order for c in self.clips) != list(range(1, count + 1)):
            raise ValueError("Playback order must be unique and contiguous 1..N")
        return self

    def in_playback_order(self) -> list[Clip]:
        """Return clips sorted by playback position."""
        return sorted(self.clips, key=lambda c: c.playback_order)


def default_document(
    project_id: str, count: int = DEFAULT_CLIP_COUNT
) -> RankingDocument:
    """Create an empty document with ``count`` blank slots."""
    clips = [Clip(rank=i, playback_order=i) for i in range(1, count + 1)]
    return RankingDocument(project_id=project_id, clips=clips)


def merge_client_document(
    stored: RankingDocument, incoming: dict[str, Any]
) -> RankingDocument:
    """Validate a client document, keeping server-owned clip fields from ``stored``.

    Clients may not set ``asset_id``, ``media`` or ``source_generation``; those are
    copied from the stored clip with the same id (new clips start unattached).

    Raises:
        ValueError: If the merged document is invalid.
    """
    payload = dict(incoming)
    payload["project_id"] = stored.project_id
    payload["schema_version"] = SCHEMA_VERSION
    stored_by_id = {c.id: c for c in stored.clips}
    clips: list[dict[str, Any]] = []
    for raw in payload.get("clips", []):
        raw = dict(raw)
        prior = stored_by_id.get(raw.get("id", ""))
        for key in ("asset_id", "media", "source_generation"):
            raw.pop(key, None)
        if prior is not None:
            raw["asset_id"] = prior.asset_id
            raw["media"] = prior.media.model_dump() if prior.media else None
            raw["source_generation"] = prior.source_generation
        clips.append(raw)
    payload["clips"] = clips
    return RankingDocument.model_validate(payload)
