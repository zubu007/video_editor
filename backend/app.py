"""FastAPI application for video editing operations."""

from __future__ import annotations

import logging
import mimetypes
import re
import shutil
import subprocess
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import aiofiles
import imageio_ffmpeg
from dotenv import load_dotenv
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from moviepy import VideoFileClip
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from backend.features.audio.extract import get_waveform_data_from_file_id
from backend.features.audio_pause.detect import (
    apply_pause_padding,
    detect_audio_pauses,
    get_total_silence_duration,
    merge_nearby_pauses,
)
from backend.features.caption_removal.jobs import (
    create_job,
    get_job,
    run_caption_removal_job,
)
from backend.features.caption_removal.remove import DEFAULT_MODE, use_gpu_from_env
from backend.features.gaming import extract_slot_previews
from backend.features.gaming.jobs import (
    create_job as create_death_detect_job,
    get_job as get_death_detect_job,
    run_death_detect_job,
)
from backend.features.transcript.jobs import (
    create_job as create_transcript_job,
    get_job as get_transcript_job,
    run_transcript_job,
)
from backend.features.gaming.highlight_jobs import (
    create_job as create_highlight_job,
    get_job as get_highlight_job,
    run_highlight_job,
)
from backend.features.captions import (
    DEFAULT_STYLE as DEFAULT_CAPTION_STYLE,
    STYLE_PRESETS as CAPTION_STYLE_PRESETS,
    add_captions,
    add_text_captions,
    output_intervals,
    remap_words,
    video_duration,
)
from backend.features.youtube.jobs import (
    create_job as create_download_job,
    get_job as get_download_job,
    run_download_job,
)
from backend.features.assistant.chat import (
    build_project_context,
    generate_chat_reply,
)
from backend.features.assistant.tools import ToolContext
from backend.features.diagram.detector import suggest_diagrams
from backend.features.diagram.renderer import get_or_render_overlay
from backend.features.diagram.schema import normalize_layout, validate_graph
from backend.features.editing_plan.feature_registry import (
    clamp_stock_footage_end,
    normalize_stock_media_type,
)
from backend.features.editing_plan.generator import generate_editing_plan
from backend.features.filler_words.detect import detect_filler_words
from backend.features.pexels.download import (
    PexelsAPIError,
    download_stock_footage,
    download_stock_media,
)
from backend.features.system.gpu import detect_gpus, detect_tool_cuda
from backend.features.transcript.extract import (
    extract_transcript_as_segments,
    extract_transcript_as_sentences,
    extract_transcript_as_words,
)
from backend.features.project_io import (
    PROJECT_FILE_EXTENSION,
    ProjectFile,
    build_project_file,
    load_project_file,
)
from backend.features.project_io.import_ import ProjectFileError
from backend.features.video_cutter.cut import (
    IMAGE_EXTENSIONS,
    cut_filler_words,
    render_timeline,
    render_with_edits,
)
from backend.features.video_cutter.jobs import (
    create_job as create_render_job,
    get_job as get_render_job,
    update_job as update_render_job,
)
from backend.storage.database import (
    EditingPlan,
    EditOperation,
    MediaAsset,
    Project,
    StockFootage,
    get_latest_editing_plan,
    get_project,
    get_session,
    get_stock_footage,
    init_db,
    touch_project,
    utc_now,
)

# Load environment variables from a .env file at the repo root (API_KEY, PEXELS_API_KEY, ...).
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Initialize local resources for the API."""
    init_db()
    yield


# Initialize FastAPI app
app = FastAPI(
    title="Video Editor API",
    description="API for automated video editing operations including transcript extraction, filler word removal, and editing plan generation",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:3000",
    ],  # Vite and CRA dev servers
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Create temp directories for uploads and outputs
UPLOAD_DIR = Path("temp/uploads")
OUTPUT_DIR = Path("temp/outputs")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_EXTENSIONS = (".mp4", ".webm", ".mov", ".avi", ".mkv")
# Chunk size for streaming uploads to disk; keeps peak memory flat regardless
# of how large the uploaded video is.
UPLOAD_CHUNK_SIZE = 1024 * 1024
# Edit operation types that can be persisted and rendered for a project.
# "diagram" overlays are rendered with Manim (transparent .mov) and composited
# over the spans they cover at project render time. "captions" burns
# shorts-style word captions over the spans it covers as a final ffmpeg pass
# after the MoviePy render. "text_caption" burns a single hand-written note
# that streams on with a typewriter reveal, as a further ffmpeg pass.
SUPPORTED_EDIT_TYPES = {
    "cut",
    "zoom",
    "insert_stock_footage",
    "diagram",
    "captions",
    "text_caption",
}

# Timeline segments are stored as EditOperation rows of this type, ordered by
# details["position"]. They are managed only through the /timeline endpoints,
# not the generic edit endpoints.
TIMELINE_EDIT_TYPE = "timeline_segment"
DEFAULT_ZOOM_LEVEL = 1.2
CONTENT_TYPE_BY_EXTENSION = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
}


# ============================================================================
# Pydantic Models
# ============================================================================


class TranscriptSegment(BaseModel):
    """Model for transcript segment."""

    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    text: str = Field(..., description="Transcript text")


class TranscriptWord(BaseModel):
    """Model for transcript word."""

    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    word: str = Field(..., description="Word text")


class FillerWordRange(BaseModel):
    """Model for filler word time range."""

    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")


class EditingDecision(BaseModel):
    """Model for editing decision."""

    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    feature: str = Field(..., description="Feature/effect to apply")
    parameters: Optional[dict] = Field(None, description="Feature parameters")
    reason: Optional[str] = Field(None, description="Reason for the decision")


class TranscriptResponse(BaseModel):
    """Response model for transcript extraction."""

    language: Optional[str] = None
    segments: list[TranscriptSegment] = []


class TranscriptWordsResponse(BaseModel):
    """Response model for word-level transcript extraction."""

    language: Optional[str] = None
    words: list[TranscriptWord] = []


class TranscriptJobStartResponse(BaseModel):
    """Response returned when a background transcription job is started."""

    job_id: str = Field(..., description="Poll this to track the job")
    status: str = Field(..., description="Job status (pending/running/done/error)")


class TranscriptJobStatusResponse(BaseModel):
    """Status of a background transcription job."""

    job_id: str
    status: str = Field(..., description="pending, running, done, or error")
    progress: float = Field(0.0, description="0.0-1.0 completion fraction")
    words: list[TranscriptWord] = []
    error: Optional[str] = None


class FillerWordsResponse(BaseModel):
    """Response model for filler word detection."""

    filler_word_ranges: list[FillerWordRange] = []
    count: int = Field(..., description="Number of filler words detected")


class EditingPlanResponse(BaseModel):
    """Response model for editing plan generation."""

    editing_plan: list[EditingDecision] = []


class DiagramNode(BaseModel):
    """Model for one node of a diagram graph spec."""

    id: str = Field(..., description="Unique node id within the graph")
    label: str = Field(..., description="Short on-screen label")
    reveal_at: Optional[float] = Field(
        None,
        description="When the node animates in, in seconds from the segment start",
    )


class DiagramEdge(BaseModel):
    """Model for one edge of a diagram graph spec."""

    source: str = Field(..., description="Id of the source node")
    target: str = Field(..., description="Id of the target node")
    label: Optional[str] = Field(None, description="Optional edge label")


class DiagramGraph(BaseModel):
    """Model for a validated diagram graph spec."""

    nodes: list[DiagramNode] = []
    edges: list[DiagramEdge] = []
    reveal_order: list[str] = Field(
        default_factory=list, description="Node ids in animation reveal order"
    )


class DiagramSuggestion(BaseModel):
    """Model for one suggested diagram overlay."""

    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    diagram_type: str = Field(
        ..., description="One of: flowchart, timeline, comparison, cycle"
    )
    title: str = Field("", description="Short on-screen title")
    transcript_excerpt: str = Field(
        "", description="Transcript text the diagram illustrates"
    )
    reason: str = Field("", description="Why this segment benefits from a diagram")
    graph: DiagramGraph


class DiagramSuggestResponse(BaseModel):
    """Response model for diagram suggestion."""

    diagrams: list[DiagramSuggestion] = []


class DiagramRenderRequest(BaseModel):
    """Request model for rendering one diagram spec to a preview video."""

    diagram_type: str = Field(
        "flowchart", description="One of: flowchart, timeline, comparison, cycle"
    )
    title: str = Field("", description="Short on-screen title")
    start: float = Field(..., description="Segment start in seconds")
    end: float = Field(..., description="Segment end in seconds")
    graph: dict = Field(
        ..., description="Graph spec with nodes, edges and reveal_order"
    )
    background: Optional[str] = Field(
        None,
        description=(
            "Background of the rendered clip: 'transparent' or omitted for the "
            "default, or a solid #rrggbb color"
        ),
    )
    layout: str = Field(
        "landscape",
        description="Orientation of the rendered clip: landscape or portrait",
    )


class DiagramRenderResponse(BaseModel):
    """Response model for a rendered diagram preview."""

    video_url: str = Field(..., description="URL of the rendered preview video")
    filename: str = Field(..., description="Rendered preview filename")
    cached: bool = Field(False, description="Whether the preview came from cache")


class StockFootageResponse(BaseModel):
    """Response model for stock footage download."""

    file_path: str = Field(..., description="Path to downloaded media file")
    search_term: str = Field(..., description="Search term used")
    media_type: str = Field(
        "video", description="Downloaded media type ('video' or 'image')"
    )


class VideoUploadResponse(BaseModel):
    """Response model for video upload."""

    file_id: str = Field(..., description="Unique file identifier")
    file_url: str = Field(..., description="URL to access the video")
    filename: str = Field(..., description="Original filename")
    size: int = Field(..., description="File size in bytes")
    duration: Optional[float] = Field(None, description="Video duration in seconds")
    project_id: str = Field(..., description="Project that owns the uploaded video")
    media_asset_id: str = Field(..., description="Stored media asset ID")


class ProjectResponse(BaseModel):
    """Response model for a project."""

    id: str
    name: str
    created_at: datetime
    updated_at: datetime


class MediaAssetResponse(BaseModel):
    """Response model for an uploaded media asset."""

    id: str
    project_id: str
    file_id: str
    filename: str
    file_url: str
    size: int
    duration: Optional[float] = None
    created_at: datetime


class EditOperationCreate(BaseModel):
    """Request model for creating a stored edit operation."""

    type: str = Field("cut", description="Edit operation type")
    source: str = Field("silence_detection", description="Tool/source that created it")
    start: float = Field(..., ge=0, description="Start time in seconds")
    end: float = Field(..., gt=0, description="End time in seconds")
    enabled: bool = Field(True, description="Whether this edit should be rendered")
    metadata: dict[str, Any] = Field(default_factory=dict)
    media_asset_id: Optional[str] = None


class EditOperationUpdate(BaseModel):
    """Request model for updating a stored edit operation."""

    enabled: Optional[bool] = None
    start: Optional[float] = Field(None, ge=0)
    end: Optional[float] = Field(None, gt=0)
    metadata: Optional[dict[str, Any]] = None


class BulkEditOperationsRequest(BaseModel):
    """Request model for creating multiple edit operations."""

    edits: list[EditOperationCreate] = Field(default_factory=list)


class EditOperationResponse(BaseModel):
    """Response model for a stored edit operation."""

    id: str
    project_id: str
    media_asset_id: Optional[str] = None
    type: str
    source: str
    start: float
    end: float
    enabled: bool
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class EditOperationsResponse(BaseModel):
    """Response model for stored edit operations."""

    edits: list[EditOperationResponse] = Field(default_factory=list)


class TimelineSegmentInput(BaseModel):
    """One ordered timeline segment (a source-time range) being saved."""

    start: float = Field(..., ge=0, description="Source start time in seconds")
    end: float = Field(..., gt=0, description="Source end time in seconds")


class TimelineUpdateRequest(BaseModel):
    """Request model replacing a project's ordered timeline segments."""

    segments: list[TimelineSegmentInput] = Field(
        default_factory=list,
        description="Ordered segments; an empty list clears the timeline",
    )
    media_asset_id: Optional[str] = None


class TimelineSegmentResponse(BaseModel):
    """Response model for one stored timeline segment."""

    id: str
    start: float
    end: float
    position: int


class TimelineResponse(BaseModel):
    """Response model for a project's ordered timeline."""

    segments: list[TimelineSegmentResponse] = Field(default_factory=list)


class AudioPauseRange(BaseModel):
    """Model for an audio pause/silence range."""

    start: float
    end: float
    duration: float


class AudioPausesResponse(BaseModel):
    """Response model for audio pause detection."""

    pauses: list[AudioPauseRange] = Field(default_factory=list)
    count: int
    total_silence_duration: float
    settings: dict[str, Any]


class RenderResponse(BaseModel):
    """Response model for a rendered project."""

    output_url: str
    filename: str
    applied_edits: int


class RenderStartResponse(BaseModel):
    """Response returned when a background render job is started."""

    job_id: str
    status: str


class RenderStatusResponse(BaseModel):
    """Status of a background render job, with the result once done."""

    job_id: str
    status: str
    progress: float = Field(
        0.0, ge=0.0, le=1.0, description="Render completion as a 0.0–1.0 fraction."
    )
    output_url: Optional[str] = None
    filename: Optional[str] = None
    applied_edits: Optional[int] = None
    error: Optional[str] = None


class CaptionStylePresetResponse(BaseModel):
    """One caption style preset, with the visual details a UI preview needs."""

    name: str
    font_family: str
    font_scale: float
    text_colour: str
    highlight_colour: Optional[str] = None
    outline_colour: str
    outline_scale: float
    shadow_scale: float
    margin_v_scale: float
    word_colours: list[str] = Field(default_factory=list)
    uppercase: bool
    pop_scale: Optional[int] = None
    max_words_per_line: int


class CaptionStylesResponse(BaseModel):
    """Response model listing the available caption style presets."""

    styles: list[CaptionStylePresetResponse]
    default_style: str


class EditingPlanSaveRequest(BaseModel):
    """Request model for saving a project's editing plan."""

    plan: list[Any] = Field(default_factory=list, description="Editing decisions")
    options: dict[str, Any] = Field(
        default_factory=dict, description="Options used to generate the plan"
    )
    media_asset_id: Optional[str] = None


class EditingPlanRecordResponse(BaseModel):
    """Response model for a stored editing plan."""

    id: str
    project_id: str
    media_asset_id: Optional[str] = None
    plan: list[Any] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class StockFootageCreate(BaseModel):
    """Request model for registering a downloaded stock-footage clip."""

    filename: str
    path: str
    source: str = "pexels"
    query: Optional[str] = None
    provider_id: Optional[str] = None
    duration: Optional[float] = None
    size: Optional[int] = None


class StockFootageRecordResponse(BaseModel):
    """Response model for a stored stock-footage clip."""

    id: str
    project_id: str
    filename: str
    path: str
    source: str
    query: Optional[str] = None
    provider_id: Optional[str] = None
    duration: Optional[float] = None
    size: Optional[int] = None
    created_at: datetime


class StockFootageListResponse(BaseModel):
    """Response model for a project's stock-footage clips."""

    footage: list[StockFootageRecordResponse] = Field(default_factory=list)


class MissingMediaResponse(BaseModel):
    """A referenced file that could not be resolved when importing a project."""

    file_id: Optional[str] = None
    filename: str
    kind: str
    expected_abs: Optional[str] = None
    expected_rel: Optional[str] = None


class ProjectImportResponse(BaseModel):
    """Response model for importing a .vedit project file."""

    project_id: str
    relinked: list[str] = Field(default_factory=list)
    missing: list[MissingMediaResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RelinkRequest(BaseModel):
    """Request model for relinking missing media to new on-disk paths."""

    media: dict[str, str] = Field(
        default_factory=dict, description="Map of file_id -> new source path"
    )


class CaptionRemovalStartResponse(BaseModel):
    """Response model for starting a caption removal job."""

    job_id: str = Field(..., description="Identifier for polling job status")
    status: str = Field(..., description="Job status (pending|running|done|error)")


class CaptionJobStatusResponse(BaseModel):
    """Response model for caption removal job status."""

    job_id: str
    status: str = Field(..., description="Job status (pending|running|done|error)")
    output_url: Optional[str] = Field(
        None, description="URL of the cleaned video when status is 'done'"
    )
    error: Optional[str] = Field(
        None, description="Failure detail when status is 'error'"
    )


class DeathDetectStartResponse(BaseModel):
    """Response model for starting a death-detection job."""

    job_id: str = Field(..., description="Identifier for polling job status")
    status: str = Field(..., description="Job status (pending|running|done|error)")


class DeathIntervalResponse(BaseModel):
    """One detected dead interval, in source-video seconds."""

    start: float
    end: float
    duration: float


class GamingEventResponse(BaseModel):
    """A K/D/A event marker at a source-video timestamp."""

    time: float
    kind: str = Field(..., description="Event kind: 'K', 'D', or 'A'")


class DeathDetectStatusResponse(BaseModel):
    """Response model for death-detection job status."""

    job_id: str
    status: str = Field(..., description="Job status (pending|running|done|error)")
    intervals: list[DeathIntervalResponse] = Field(default_factory=list)
    events: list[GamingEventResponse] = Field(
        default_factory=list,
        description="K/D/A markers for the play bar, in source seconds",
    )
    player_slot: Optional[int] = Field(
        None, description="0-based top-bar slot used for detection"
    )
    confidence: Optional[float] = Field(
        None,
        description="Auto-identification confidence in [0, 1] (null if overridden)",
    )
    kda_available: bool = Field(
        False,
        description=(
            "Whether the K/A OCR pass ran (tesseract available). When false, only "
            "death markers are produced even if K/D/A was requested."
        ),
    )
    error: Optional[str] = Field(
        None, description="Failure detail when status is 'error'"
    )


class HighlightClipRequest(BaseModel):
    """Request to trim a quick highlight clip from a source recording."""

    start: float = Field(..., ge=0, description="Clip start in source seconds")
    end: float = Field(..., gt=0, description="Clip end in source seconds")


class HighlightClipResponse(BaseModel):
    """A trimmed highlight clip ready for download/preview."""

    filename: str
    output_url: str = Field(..., description="URL to fetch the clip from")
    duration: float = Field(..., description="Clip length in seconds")


class HighlightClipStartResponse(BaseModel):
    """Response returned when a background highlight-clip job is started."""

    job_id: str = Field(..., description="Poll this to track the job")
    status: str = Field(..., description="Job status (pending/running/done/error)")


class HighlightClipStatusResponse(BaseModel):
    """Status of a background highlight-clip job."""

    job_id: str
    status: str = Field(..., description="pending, running, done, or error")
    filename: Optional[str] = None
    output_url: Optional[str] = Field(
        None, description="Clip URL once status is 'done'"
    )
    duration: float = Field(0.0, description="Clip length in seconds")
    error: Optional[str] = None


class SlotPreviewResponse(BaseModel):
    """Auto-identified slot plus base64 portrait thumbnails for the slot picker."""

    team: str
    auto_slot: int = Field(..., description="Auto-identified slot, or -1 if unsure")
    confidence: float
    slots: list[str] = Field(
        default_factory=list,
        description="Per-slot PNG thumbnails as data URLs, in slot order",
    )


class YouTubeDownloadRequest(BaseModel):
    """Request model for importing a video from YouTube."""

    url: str = Field(..., description="YouTube video URL")
    project_id: Optional[str] = Field(
        None, description="Existing project to attach the imported video to"
    )
    project_name: Optional[str] = Field(
        None, description="Name for a new project (defaults to the video title)"
    )


class YouTubeDownloadStartResponse(BaseModel):
    """Response model for starting a YouTube download job."""

    job_id: str = Field(..., description="Identifier for polling job status")
    status: str = Field(..., description="Job status (pending|running|done|error)")


class YouTubeDownloadStatusResponse(BaseModel):
    """Response model for YouTube download job status.

    Once ``status`` is ``done``, the ``file_id`` / ``project_id`` / ``media_asset_id``
    fields mirror a direct upload so the client can continue the normal editing flow.
    """

    job_id: str
    status: str = Field(..., description="Job status (pending|running|done|error)")
    progress: float = Field(0.0, description="Download progress as a 0..1 fraction")
    file_id: Optional[str] = Field(
        None, description="Uploaded file ID when status is 'done'"
    )
    project_id: Optional[str] = Field(
        None, description="Owning project ID when status is 'done'"
    )
    media_asset_id: Optional[str] = Field(
        None, description="Stored media asset ID when status is 'done'"
    )
    error: Optional[str] = Field(
        None, description="Failure detail when status is 'error'"
    )


class GpuInfoResponse(BaseModel):
    """A single detected GPU."""

    name: str = Field(..., description="GPU model name")
    memory_total_mb: Optional[int] = Field(
        None, description="Total GPU memory in MiB, if reported"
    )


class ToolCudaResponse(BaseModel):
    """Whether the caption-removal tool's venv can actually use CUDA."""

    checked: bool = Field(..., description="Whether the probe could run")
    available: bool = Field(
        ..., description="Whether torch.cuda is available in the tool's venv"
    )
    device_name: Optional[str] = Field(
        None, description="CUDA device name reported by the tool's venv"
    )
    detail: str = Field(..., description="Human-readable probe summary")


class GpuDetectionResponse(BaseModel):
    """Response model for host GPU detection."""

    available: bool = Field(..., description="Whether a usable NVIDIA GPU was detected")
    gpus: list[GpuInfoResponse] = Field(default_factory=list)
    detail: str = Field(..., description="Human-readable detection summary")
    tool: ToolCudaResponse = Field(
        ..., description="Whether the caption-removal tool's venv can use the GPU"
    )


class EditingPlanRequest(BaseModel):
    """Request model for file-id based editing plan generation."""

    model_size: str = Field("base", description="Whisper model size")
    api_key: Optional[str] = Field(None, description="Groq API key")
    llm_model: str = Field(
        "llama-3.3-70b-versatile", description="Groq LLM model to use"
    )
    additional_context: str = Field(
        "", description="Additional context or instructions"
    )


class DiagramSuggestRequest(BaseModel):
    """Request model for file-id based diagram suggestion."""

    model_size: str = Field("base", description="Whisper model size")
    api_key: Optional[str] = Field(None, description="Groq API key")
    llm_model: str = Field(
        "llama-3.3-70b-versatile", description="Groq LLM model to use"
    )
    additional_context: str = Field(
        "", description="Additional context or instructions"
    )


class ChatMessage(BaseModel):
    """One message in the project assistant conversation."""

    role: str = Field(..., description="Message role: 'user' or 'assistant'")
    content: str = Field(..., description="Message text")


class ProjectChatRequest(BaseModel):
    """Request model for the project assistant chat."""

    messages: list[ChatMessage] = Field(
        ...,
        description="Conversation history, oldest first, ending with the user message",
    )
    transcript: str = Field(
        "", description="Plain-text transcript of the source video (optional)"
    )
    activity_log: list[str] = Field(
        default_factory=list,
        description="Recent editor activity lines shown in the chat (oldest first)",
    )
    api_key: Optional[str] = Field(None, description="Groq API key")
    llm_model: str = Field(
        "llama-3.3-70b-versatile", description="Groq LLM model to use"
    )


class ChatActionResponse(BaseModel):
    """One tool call the assistant executed while answering."""

    tool: str = Field(..., description="Name of the tool that ran")
    summary: str = Field(..., description="Human-readable outcome")
    ok: bool = Field(..., description="Whether the tool call succeeded")


class ProjectChatResponse(BaseModel):
    """Response model for the project assistant chat."""

    reply: str = Field(..., description="Assistant reply text")
    actions: list[ChatActionResponse] = Field(
        default_factory=list,
        description="Tool calls the assistant executed, in order",
    )
    edits_changed: bool = Field(
        False,
        description="True when the assistant changed the project's saved edits",
    )


class WaveformResponse(BaseModel):
    """Response model for waveform data."""

    waveform: list[float] = Field(
        ..., description="Array of peak amplitude values (0.0 to 1.0)"
    )
    duration: float = Field(..., description="Audio duration in seconds")
    sample_rate: int = Field(..., description="Audio sample rate in Hz")
    num_samples: int = Field(..., description="Number of samples in waveform array")


# ============================================================================
# Helper Functions
# ============================================================================


async def save_upload_file(upload_file: UploadFile, destination: Path) -> None:
    """Save an uploaded file to disk.

    Copied in chunks rather than via a single ``read()``: uploads are whole
    videos, and reading one into a single ``bytes`` object costs its full size
    in resident memory (a 4K source is comfortably several GB).

    Args:
        upload_file: The incoming multipart file.
        destination: Path to write the bytes to.
    """
    async with aiofiles.open(destination, "wb") as f:
        while chunk := await upload_file.read(UPLOAD_CHUNK_SIZE):
            await f.write(chunk)


def temp_upload_path(filename: str) -> Path:
    """Build a safe, collision-free path under ``UPLOAD_DIR`` for an upload.

    ``filename`` is supplied by the client and is never trusted: the stored
    name is a fresh UUID and only a conservative extension is carried over.
    Joining the raw name would let ``../../../tmp/evil`` write outside
    ``UPLOAD_DIR`` — and, via the callers' ``finally`` cleanup, unlink an
    arbitrary existing file.

    Args:
        filename: The client-supplied upload filename.

    Returns:
        A path inside ``UPLOAD_DIR`` that no other request can collide with.
    """
    suffix = Path(filename).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
        suffix = ""
    return UPLOAD_DIR / f"upload_{uuid.uuid4().hex}{suffix}"


def safe_download_name(filename: str, fallback: str = "video.mp4") -> str:
    """Reduce a client-supplied filename to one safe to join and serve.

    Strips any directory components and replaces everything outside a plain
    ``[A-Za-z0-9._-]`` set, so the result is a single path segment usable both
    as an ``OUTPUT_DIR`` name and as a ``Content-Disposition`` filename.

    Args:
        filename: The client-supplied filename.
        fallback: Name to use when nothing usable survives sanitizing.

    Returns:
        A single safe path segment.
    """
    name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name).lstrip(".")
    return name or fallback


def find_uploaded_video(file_id: str) -> Path:
    """Find an uploaded video by file ID."""
    for ext in VIDEO_EXTENSIONS:
        candidate = UPLOAD_DIR / f"{file_id}{ext}"
        if candidate.exists():
            return candidate

    raise FileNotFoundError(f"Video not found for file_id: {file_id}")


def resolve_media_path(file_id: str) -> Path | None:
    """Return the on-disk path for a file_id, or None if it cannot be found."""
    try:
        return find_uploaded_video(file_id)
    except FileNotFoundError:
        return None


def get_video_duration(video_path: Path) -> float | None:
    """Read video duration when metadata is available."""
    video = None
    try:
        video = VideoFileClip(str(video_path))
        return float(video.duration)
    except HTTPException:
        if video_path.exists():
            video_path.unlink()
        raise
    except Exception as e:
        logger.warning("Could not read duration for %s: %s", video_path, e)
        return None
    finally:
        if video is not None:
            video.close()


def remux_video_in_place(video_path: Path) -> bool:
    """Rewrite the media container in place to restore missing metadata.

    Browser ``MediaRecorder`` output (notably Chrome's WebM) lacks duration
    and seek cues in its container header, which breaks duration probing and
    player seeking. A stream-copy remux through ffmpeg rewrites the container
    with correct metadata without re-encoding.

    Returns:
        True if the file was rewritten, False if the remux failed (the
        original file is left untouched).
    """
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    remuxed_path = video_path.with_name(f"{video_path.stem}.remux{video_path.suffix}")
    command = [ffmpeg, "-y", "-i", str(video_path), "-c", "copy", str(remuxed_path)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("Remux failed for %s: %s", video_path, e)
        remuxed_path.unlink(missing_ok=True)
        return False

    if result.returncode != 0 or not remuxed_path.exists():
        logger.warning(
            "Remux failed for %s: %s",
            video_path,
            (result.stderr or "")[-500:],
        )
        remuxed_path.unlink(missing_ok=True)
        return False

    remuxed_path.replace(video_path)
    return True


# Relative gap between declared and measured frame rate above which a video is
# treated as variable frame rate. Container quirks (29.97 declared vs 30
# measured) stay well below it; MediaRecorder screen captures (30 declared vs
# ~16 measured) far exceed it.
VFR_MISMATCH_TOLERANCE = 0.10

_STREAM_RATE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)(k?)\s*(fps|tbr)\b")


def parse_stream_frame_rates(ffmpeg_output: str) -> tuple[float | None, float | None]:
    """Parse frame rates from ffmpeg's stream-info output.

    ffmpeg's ``-i`` banner reports two rates for a video stream, e.g.
    ``16.57 fps, 30 tbr``: ``fps`` is the measured average frame rate and
    ``tbr`` the declared (container) rate. On a constant-frame-rate file they
    match; on variable-frame-rate output (browser ``MediaRecorder``) they
    diverge.

    Args:
        ffmpeg_output (str): stderr text from an ``ffmpeg -i`` invocation.

    Returns:
        ``(average_fps, declared_fps)``, either value ``None`` when absent.
    """
    average_fps: float | None = None
    declared_fps: float | None = None
    for value, kilo, label in _STREAM_RATE_PATTERN.findall(ffmpeg_output):
        rate = float(value) * (1000.0 if kilo else 1.0)
        if label == "fps" and average_fps is None:
            average_fps = rate
        elif label == "tbr" and declared_fps is None:
            declared_fps = rate
    return average_fps, declared_fps


_COPY_STATS_PATTERN = re.compile(r"frame=\s*(\d+).*?time=(\d+):(\d+):(\d+(?:\.\d+)?)")


def parse_copy_stats(ffmpeg_output: str) -> tuple[int | None, float | None]:
    """Parse ``(frame_count, stream_seconds)`` from an ffmpeg progress line.

    A stream-copy pass ends with a progress line such as
    ``frame= 1529 ... time=00:01:32.63 ...``; the last such line holds the
    stream's total packet count and demuxed duration.
    """
    matches = _COPY_STATS_PATTERN.findall(ffmpeg_output)
    if not matches:
        return None, None
    frames, hours, minutes, seconds = matches[-1]
    total_seconds = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return int(frames), total_seconds


def probe_frame_rates(video_path: Path) -> tuple[float | None, float | None]:
    """Probe a video's measured and declared frame rates via ffmpeg.

    The declared rate comes from the stream banner (``tbr``, falling back to
    the banner ``fps``). The measured rate is computed by counting the video
    stream's packets in a stream-copy pass (no decode, near-instant): the
    banner ``fps`` alone cannot be trusted, because Matroska/WebM — the
    container browsers record into — echoes the declared rate even for
    variable-frame-rate content.

    Returns:
        ``(average_fps, declared_fps)``; either value ``None`` when probing
        fails.
    """
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-i",
                str(video_path),
                "-map",
                "0:v:0",
                "-c",
                "copy",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("Frame-rate probe failed for %s: %s", video_path, e)
        return None, None

    output = result.stderr or ""
    banner_fps, declared_fps = parse_stream_frame_rates(output)
    if declared_fps is None:
        declared_fps = banner_fps

    average_fps = banner_fps
    frames, seconds = parse_copy_stats(output)
    if frames and seconds and seconds > 0.1:
        average_fps = frames / seconds
    return average_fps, declared_fps


def is_variable_frame_rate(
    average_fps: float | None, declared_fps: float | None
) -> bool:
    """Return True when measured and declared frame rates diverge enough."""
    if not average_fps or not declared_fps:
        return False
    return abs(declared_fps - average_fps) / declared_fps > VFR_MISMATCH_TOLERANCE


def target_constant_fps(declared_fps: float | None) -> float:
    """Pick the constant frame rate to normalize a VFR video to."""
    if declared_fps and 5.0 <= declared_fps <= 120.0:
        return declared_fps
    return 30.0


def normalize_frame_rate(video_path: Path, target_fps: float) -> Path | None:
    """Re-encode a video to a constant frame rate.

    MoviePy assumes constant frame spacing when it maps timestamps to frame
    indices, so variable-frame-rate sources drift out of sync with their audio
    during rendering. This re-encodes the video stream onto a uniform
    ``target_fps`` grid (H.264 in an mp4 container, audio re-encoded to AAC)
    and replaces the original file. Because the output container is always
    mp4, a non-mp4 source (e.g. ``.webm``) is replaced by its ``.mp4``
    sibling and the original deleted.

    Args:
        video_path (Path): Video to normalize in place.
        target_fps (float): Constant frame rate for the output.

    Returns:
        Path of the normalized file, or ``None`` if the re-encode failed
        (the original file is left untouched).
    """
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    encode_path = video_path.with_name(f"{video_path.stem}.cfr.mp4")
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(video_path),
        # Even dimensions are required by yuv420p; window captures can be odd.
        "-vf",
        f"fps={target_fps:g},scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(encode_path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("Frame-rate normalization failed for %s: %s", video_path, e)
        encode_path.unlink(missing_ok=True)
        return None

    if result.returncode != 0 or not encode_path.exists():
        logger.warning(
            "Frame-rate normalization failed for %s: %s",
            video_path,
            (result.stderr or "")[-500:],
        )
        encode_path.unlink(missing_ok=True)
        return None

    final_path = video_path.with_suffix(".mp4")
    if final_path != video_path:
        video_path.unlink(missing_ok=True)
    encode_path.replace(final_path)
    return final_path


def ensure_constant_frame_rate(video_path: Path) -> Path:
    """Normalize a video to constant frame rate when it is detected as VFR.

    Returns:
        The path to use from here on: the normalized file when a re-encode
        happened (its extension may differ from the input), otherwise the
        original path.
    """
    average_fps, declared_fps = probe_frame_rates(video_path)
    if not is_variable_frame_rate(average_fps, declared_fps):
        return video_path

    target = target_constant_fps(declared_fps)
    logger.info(
        "VFR source %s (%.2f fps measured vs %.2f declared); normalizing to %g fps",
        video_path.name,
        average_fps,
        declared_fps,
        target,
    )
    normalized = normalize_frame_rate(video_path, target)
    return normalized or video_path


def file_response_for_video(
    video_path: Path, filename: str | None = None
) -> FileResponse:
    """Build a FileResponse for a video path."""
    content_type = CONTENT_TYPE_BY_EXTENSION.get(video_path.suffix, "video/mp4")
    return FileResponse(
        path=video_path,
        media_type=content_type,
        filename=filename or video_path.name,
    )


def edit_operation_to_response(edit: EditOperation) -> EditOperationResponse:
    """Convert a stored edit operation into its API response shape."""
    return EditOperationResponse(
        id=edit.id,
        project_id=edit.project_id,
        media_asset_id=edit.media_asset_id,
        type=edit.type,
        source=edit.source,
        start=edit.start,
        end=edit.end,
        enabled=edit.enabled,
        metadata=edit.details or {},
        created_at=edit.created_at,
        updated_at=edit.updated_at,
    )


def validate_cut_range(start: float, end: float) -> None:
    """Validate a cut time range."""
    if start < 0 or end <= start:
        raise HTTPException(
            status_code=400, detail="Edit range must satisfy 0 <= start < end"
        )


def validate_captions_metadata(edit_type: str, metadata: dict | None) -> None:
    """Reject a captions edit that names an unknown style preset."""
    if edit_type != "captions":
        return
    style = (metadata or {}).get("style")
    if style is not None and style not in CAPTION_STYLE_PRESETS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown caption style '{style}'. "
            f"Available styles: {', '.join(sorted(CAPTION_STYLE_PRESETS))}",
        )


# Where a manual text caption may sit on the frame.
TEXT_CAPTION_POSITIONS = {"top", "middle", "bottom"}


def validate_text_caption_metadata(edit_type: str, metadata: dict | None) -> None:
    """Reject a text-caption edit with no text or an invalid position."""
    if edit_type != "text_caption":
        return
    details = metadata or {}
    if not str(details.get("text", "")).strip():
        raise HTTPException(
            status_code=400,
            detail="A text caption needs non-empty 'text'.",
        )
    position = details.get("position")
    if position is not None and position not in TEXT_CAPTION_POSITIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown caption position '{position}'. "
            f"Valid positions: {', '.join(sorted(TEXT_CAPTION_POSITIONS))}",
        )


def ensure_project(session: Session, project_id: str) -> Project:
    """Return a project or raise a 404 response."""
    project = get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


# ============================================================================
# Video Upload/Serving Endpoints
# ============================================================================


@app.post("/api/video/upload", response_model=VideoUploadResponse)
async def upload_video(
    video: UploadFile = File(..., description="Video file to upload"),
    project_id: Optional[str] = Form(None, description="Existing project ID"),
    project_name: Optional[str] = Form(None, description="Project name"),
    session: Session = Depends(get_session),
):
    """
    Upload a video file to the server.

    The video will be stored and assigned a unique ID for later retrieval.
    """
    if not video.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    # Generate unique file ID
    file_id = str(uuid.uuid4())
    file_extension = Path(video.filename).suffix
    stored_filename = f"{file_id}{file_extension}"
    video_path = UPLOAD_DIR / stored_filename

    try:
        # Save uploaded file
        logger.info(f"Uploading video: {video.filename} as {stored_filename}")
        await save_upload_file(video, video_path)

        duration = get_video_duration(video_path)
        if duration is None:
            # Typical for in-browser recordings (MediaRecorder): the container
            # has no duration/seek metadata until it is remuxed.
            logger.info(
                "No duration metadata for %s; remuxing container", stored_filename
            )
            if remux_video_in_place(video_path):
                duration = get_video_duration(video_path)

        # Browser MediaRecorder captures are variable frame rate, which makes
        # MoviePy renders drift out of A/V sync; normalize before anything
        # downstream (transcription, waveform, render) reads the file.
        normalized_path = ensure_constant_frame_rate(video_path)
        if normalized_path != video_path:
            video_path = normalized_path
            duration = get_video_duration(video_path)

        file_size = video_path.stat().st_size
        file_url = f"/api/video/{file_id}"

        if project_id:
            project = get_project(session, project_id)
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")
        else:
            project = Project(name=project_name or Path(video.filename).stem)
            session.add(project)
            session.commit()
            session.refresh(project)

        media_asset = MediaAsset(
            project_id=project.id,
            file_id=file_id,
            filename=video.filename,
            file_url=file_url,
            size=file_size,
            duration=duration,
        )
        session.add(media_asset)
        touch_project(session, project)
        session.commit()
        session.refresh(media_asset)

        return VideoUploadResponse(
            file_id=file_id,
            file_url=file_url,
            filename=video.filename,
            size=file_size,
            duration=duration,
            project_id=project.id,
            media_asset_id=media_asset.id,
        )

    except Exception as e:
        logger.error(f"Error uploading video: {e}")
        # Clean up on error
        if video_path.exists():
            video_path.unlink()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/video/{file_id}")
async def get_video(file_id: str):
    """
    Get a video file by its ID with streaming support.

    Supports HTTP Range requests for seeking.
    """
    try:
        video_path = find_uploaded_video(file_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Video not found")

    return file_response_for_video(video_path)


@app.get("/api/audio/waveform/{file_id}", response_model=WaveformResponse)
async def get_waveform(
    file_id: str,
    num_samples: int = 2000,
):
    """
    Get waveform data for a video file by its ID.

    Extracts audio from the video and generates downsampled amplitude data
    optimized for visualization in the frontend.

    Args:
        file_id: Unique file identifier from video upload
        num_samples: Number of waveform samples to generate (default: 2000)

    Returns:
        Waveform data including amplitude array, duration, and sample rate
    """
    try:
        logger.info(f"Extracting waveform for file_id: {file_id}")
        waveform_data = get_waveform_data_from_file_id(file_id, UPLOAD_DIR, num_samples)

        return WaveformResponse(**waveform_data)

    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))

    except ValueError as e:
        logger.error(f"Invalid video file: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        logger.error(f"Error extracting waveform: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/audio/pauses/{file_id}", response_model=AudioPausesResponse)
async def get_audio_pauses(
    file_id: str,
    min_silence_duration: float = 1.0,
    silence_threshold: int = -40,
    seek_step: int = 10,
    merge_gap: Optional[float] = 0.5,
    padding: float = 0.1,
):
    """Detect silence/pause ranges for a previously uploaded video."""
    if padding < 0:
        raise HTTPException(status_code=400, detail="padding must be >= 0")

    try:
        video_path = find_uploaded_video(file_id)
        pauses = detect_audio_pauses(
            str(video_path),
            min_silence_duration=min_silence_duration,
            silence_threshold=silence_threshold,
            seek_step=seek_step,
        )

        if merge_gap is not None:
            pauses = merge_nearby_pauses(pauses, max_gap=merge_gap)

        # Leave a cushion at each edge so cuts don't land flush against speech.
        pauses = apply_pause_padding(pauses, padding=padding)

        return AudioPausesResponse(
            pauses=pauses,
            count=len(pauses),
            total_silence_duration=get_total_silence_duration(pauses),
            settings={
                "min_silence_duration": min_silence_duration,
                "silence_threshold": silence_threshold,
                "seek_step": seek_step,
                "merge_gap": merge_gap,
                "padding": padding,
            },
        )
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        logger.error(f"Invalid audio pause request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error detecting audio pauses: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Project/Edit Storage Endpoints
# ============================================================================


@app.get("/api/projects/{project_id}", response_model=ProjectResponse)
async def get_project_endpoint(
    project_id: str,
    session: Session = Depends(get_session),
):
    """Get project metadata."""
    project = ensure_project(session, project_id)
    return ProjectResponse(
        id=project.id,
        name=project.name,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@app.get("/api/projects/{project_id}/edits", response_model=EditOperationsResponse)
async def get_project_edits(
    project_id: str,
    session: Session = Depends(get_session),
):
    """Get stored edit operations for a project."""
    ensure_project(session, project_id)
    statement = (
        select(EditOperation)
        .where(EditOperation.project_id == project_id)
        .order_by(EditOperation.start, EditOperation.created_at)
    )
    edits = session.exec(statement).all()
    return EditOperationsResponse(
        edits=[edit_operation_to_response(edit) for edit in edits]
    )


@app.post(
    "/api/projects/{project_id}/edits/bulk", response_model=EditOperationsResponse
)
async def create_project_edits_bulk(
    project_id: str,
    request: BulkEditOperationsRequest,
    session: Session = Depends(get_session),
):
    """Create multiple stored edit operations for a project."""
    project = ensure_project(session, project_id)
    created_edits = []

    for edit_request in request.edits:
        validate_cut_range(edit_request.start, edit_request.end)
        if edit_request.type not in SUPPORTED_EDIT_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported edit type '{edit_request.type}'. "
                f"Supported types: {', '.join(sorted(SUPPORTED_EDIT_TYPES))}",
            )
        validate_captions_metadata(edit_request.type, edit_request.metadata)
        validate_text_caption_metadata(edit_request.type, edit_request.metadata)

        edit = EditOperation(
            project_id=project_id,
            media_asset_id=edit_request.media_asset_id,
            type=edit_request.type,
            source=edit_request.source,
            start=edit_request.start,
            end=edit_request.end,
            enabled=edit_request.enabled,
            details=edit_request.metadata,
        )
        session.add(edit)
        created_edits.append(edit)

    touch_project(session, project)
    session.commit()
    for edit in created_edits:
        session.refresh(edit)

    return EditOperationsResponse(
        edits=[edit_operation_to_response(edit) for edit in created_edits]
    )


@app.patch(
    "/api/projects/{project_id}/edits/{edit_id}", response_model=EditOperationResponse
)
async def update_project_edit(
    project_id: str,
    edit_id: str,
    request: EditOperationUpdate,
    session: Session = Depends(get_session),
):
    """Update a stored edit operation."""
    project = ensure_project(session, project_id)
    edit = session.get(EditOperation, edit_id)
    if not edit or edit.project_id != project_id:
        raise HTTPException(status_code=404, detail="Edit not found")

    if request.start is not None:
        edit.start = request.start
    if request.end is not None:
        edit.end = request.end
    validate_cut_range(edit.start, edit.end)

    if request.enabled is not None:
        edit.enabled = request.enabled
    if request.metadata is not None:
        validate_captions_metadata(edit.type, request.metadata)
        validate_text_caption_metadata(edit.type, request.metadata)
        edit.details = request.metadata

    edit.updated_at = utc_now()
    session.add(edit)
    touch_project(session, project)
    session.commit()
    session.refresh(edit)
    return edit_operation_to_response(edit)


@app.delete("/api/projects/{project_id}/edits/{edit_id}")
async def delete_project_edit(
    project_id: str,
    edit_id: str,
    session: Session = Depends(get_session),
):
    """Delete a stored edit operation."""
    project = ensure_project(session, project_id)
    edit = session.get(EditOperation, edit_id)
    if not edit or edit.project_id != project_id:
        raise HTTPException(status_code=404, detail="Edit not found")

    session.delete(edit)
    touch_project(session, project)
    session.commit()
    return {"status": "deleted"}


def _timeline_segment_rows(session: Session, project_id: str) -> list[EditOperation]:
    """Return a project's timeline segments ordered by their saved position."""
    rows = session.exec(
        select(EditOperation).where(
            EditOperation.project_id == project_id,
            EditOperation.type == TIMELINE_EDIT_TYPE,
        )
    ).all()
    return sorted(rows, key=lambda row: (row.details or {}).get("position", 0))


def _timeline_response(rows: list[EditOperation]) -> TimelineResponse:
    """Convert ordered timeline segment rows into the API response shape."""
    return TimelineResponse(
        segments=[
            TimelineSegmentResponse(
                id=row.id,
                start=row.start,
                end=row.end,
                position=(row.details or {}).get("position", index),
            )
            for index, row in enumerate(rows)
        ]
    )


@app.get("/api/projects/{project_id}/timeline", response_model=TimelineResponse)
async def get_project_timeline(
    project_id: str,
    session: Session = Depends(get_session),
):
    """Get a project's ordered timeline segments (empty if none saved)."""
    ensure_project(session, project_id)
    return _timeline_response(_timeline_segment_rows(session, project_id))


@app.put("/api/projects/{project_id}/timeline", response_model=TimelineResponse)
async def save_project_timeline(
    project_id: str,
    request: TimelineUpdateRequest,
    session: Session = Depends(get_session),
):
    """Replace a project's ordered timeline segments.

    The request's segment order is the playback order. Saving an empty list
    clears the timeline, restoring the default cut-based render.
    """
    project = ensure_project(session, project_id)
    for segment in request.segments:
        validate_cut_range(segment.start, segment.end)

    for row in _timeline_segment_rows(session, project_id):
        session.delete(row)

    created: list[EditOperation] = []
    for position, segment in enumerate(request.segments):
        row = EditOperation(
            project_id=project_id,
            media_asset_id=request.media_asset_id,
            type=TIMELINE_EDIT_TYPE,
            source="timeline",
            start=segment.start,
            end=segment.end,
            enabled=True,
            details={"position": position},
        )
        session.add(row)
        created.append(row)

    touch_project(session, project)
    session.commit()
    for row in created:
        session.refresh(row)

    return _timeline_response(created)


def _burn_project_captions(
    source_path: Path,
    rendered_path: Path,
    output_path: Path,
    captions_edits: list[EditOperation],
    cut_ranges: list,
    timeline_rows: list[EditOperation],
) -> None:
    """Burn word captions onto a rendered project video.

    Words come from the first captions edit's saved ``details["words"]``
    (falling back to transcribing the source), are filtered to the spans the
    captions edits cover, and are remapped from source time onto the rendered
    output's timeline before burning. The style also comes from the first
    captions edit. When every captioned word was cut away, the rendered video
    is kept as-is.
    """
    details = captions_edits[0].details or {}
    words = details.get("words") or extract_transcript_as_words(
        str(source_path), "base"
    )

    spans = [(edit.start, edit.end) for edit in captions_edits]
    covered = [
        word
        for word in words
        if any(
            start <= (float(word["start"]) + float(word["end"])) / 2.0 < end
            for start, end in spans
        )
    ]

    segments = [{"start": row.start, "end": row.end} for row in timeline_rows]
    intervals = output_intervals(
        video_duration(source_path), cut_ranges, segments or None
    )
    remapped = remap_words(covered, intervals)
    if not remapped:
        logger.warning("All captioned words were cut; rendering without captions")
        rendered_path.replace(output_path)
        return

    add_captions(
        rendered_path,
        remapped,
        output_path,
        style=details.get("style", DEFAULT_CAPTION_STYLE),
        max_words_per_line=details.get("max_words_per_line"),
    )
    rendered_path.unlink(missing_ok=True)


def _burn_project_text_captions(
    source_path: Path,
    rendered_path: Path,
    output_path: Path,
    text_caption_edits: list[EditOperation],
    cut_ranges: list,
    timeline_rows: list[EditOperation],
) -> None:
    """Burn hand-written streaming captions onto a rendered project video.

    Each edit's ``details["text"]`` is anchored at the edit's source-time span;
    the span is remapped onto the rendered output's timeline (mirroring cuts and
    a saved timeline) so a note streams on at the moment it was placed. Captions
    whose span was entirely cut away are dropped; if none survive the rendered
    video is kept as-is.
    """
    segments = [{"start": row.start, "end": row.end} for row in timeline_rows]
    intervals = output_intervals(
        video_duration(source_path), cut_ranges, segments or None
    )
    # Remap each caption's span onto the output timeline by the interval holding
    # its midpoint (mirroring remap_words), keeping the note's text and options.
    # Done inline rather than via remap_words so a caption stays tied to its
    # edit — remap_words drops cut spans and re-sorts, breaking that pairing.
    captions: list[dict] = []
    for edit in text_caption_edits:
        details = edit.details or {}
        text = str(details.get("text", ""))
        if not text.strip():
            continue
        midpoint = (edit.start + edit.end) / 2.0
        for interval in intervals:
            if interval["source_start"] <= midpoint < interval["source_end"]:
                offset = interval["output_start"] - interval["source_start"]
                captions.append(
                    {
                        "start": max(edit.start, interval["source_start"]) + offset,
                        "end": min(edit.end, interval["source_end"]) + offset,
                        "text": text,
                        "position": details.get("position"),
                        "reveal_seconds": details.get("reveal_seconds"),
                    }
                )
                break
    if not captions:
        logger.warning("All text captions were cut; rendering without them")
        rendered_path.replace(output_path)
        return

    add_text_captions(rendered_path, captions, output_path)
    rendered_path.unlink(missing_ok=True)


@app.post("/api/projects/{project_id}/render", response_model=RenderStartResponse)
async def render_project(
    project_id: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    """Start a background render of a project's enabled edits.

    Validates that the project, its media asset, and the source file all exist so
    the client gets immediate feedback, then runs the encode in a worker thread.
    Poll ``/api/render/status/{job_id}`` for progress and the final download URL.
    """
    ensure_project(session, project_id)

    media_asset = session.exec(
        select(MediaAsset)
        .where(MediaAsset.project_id == project_id)
        .order_by(MediaAsset.created_at)
    ).first()
    if not media_asset:
        raise HTTPException(status_code=404, detail="Project has no media asset")

    try:
        find_uploaded_video(media_asset.file_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    job = create_render_job(project_id)
    # Hand the worker the engine backing this request's session so it can open its
    # own session on the same database (the request's session is closed by the time
    # the background task runs). Using the request's bind keeps tests, which swap in
    # an in-memory engine via the get_session override, working transparently.
    background_tasks.add_task(
        _run_render_job, job.job_id, project_id, session.get_bind()
    )
    logger.info("Started render job %s for project %s", job.job_id, project_id)
    return RenderStartResponse(job_id=job.job_id, status=job.status)


@app.get("/api/render/status/{job_id}", response_model=RenderStatusResponse)
async def get_render_status(job_id: str):
    """Return the status, progress, and (once done) result of a render job."""
    job = get_render_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Render job not found")

    return RenderStatusResponse(
        job_id=job.job_id,
        status=job.status,
        progress=job.progress,
        output_url=job.output_url,
        filename=job.filename,
        applied_edits=job.applied_edits,
        error=job.error,
    )


def _run_render_job(job_id: str, project_id: str, bind: Any) -> None:
    """Render a project in a background worker thread, updating job progress.

    Opens its own database session on ``bind`` (the engine from the originating
    request, since that request's session is gone by the time this runs), resolves
    the enabled edits into concrete render inputs, encodes the video while
    forwarding frame progress to the job, and records the result or any error on
    the job for the poller.
    """
    update_render_job(job_id, status="running", progress=0.0)
    try:
        with Session(bind) as session:
            _execute_render(job_id, project_id, session)
    except Exception as e:  # noqa: BLE001 - record any failure for the poller
        logger.error("Render job %s failed: %s", job_id, e)
        update_render_job(job_id, status="error", error=str(e))


def _execute_render(job_id: str, project_id: str, session: Session) -> None:
    """Resolve a project's edits and encode the final video (see _run_render_job)."""
    media_asset = session.exec(
        select(MediaAsset)
        .where(MediaAsset.project_id == project_id)
        .order_by(MediaAsset.created_at)
    ).first()
    if not media_asset:
        raise FileNotFoundError("Project has no media asset")

    video_path = find_uploaded_video(media_asset.file_id)

    edits = session.exec(
        select(EditOperation)
        .where(
            EditOperation.project_id == project_id,
            EditOperation.enabled == True,  # noqa: E712
        )
        .order_by(EditOperation.start)
    ).all()

    cut_ranges = [
        {"start": edit.start, "end": edit.end} for edit in edits if edit.type == "cut"
    ]
    zoom_ranges = [
        {
            "start": edit.start,
            "end": edit.end,
            "level": float((edit.details or {}).get("zoom_level", DEFAULT_ZOOM_LEVEL)),
        }
        for edit in edits
        if edit.type == "zoom"
    ]

    # Resolve each stock-footage edit's search query to a downloaded clip,
    # caching downloads per (media type, query) so repeated queries hit Pexels
    # once. A failed download is skipped (logged) rather than failing the whole
    # render. Every span is cut down to its attention-span limit (5s for video
    # B-roll, 3s for a still image) regardless of how long the edit is.
    stock_footage_ranges: list[dict[str, Any]] = []
    footage_by_query: dict[tuple[str, str], str] = {}
    for edit in edits:
        if edit.type != "insert_stock_footage":
            continue
        details = edit.details or {}
        saved_path = details.get("footage_path")
        media_type = details.get("media_type")
        if not media_type and saved_path:
            # Older edits saved before media_type existed: infer from the file.
            suffix = Path(saved_path).suffix.lower()
            media_type = "image" if suffix in IMAGE_EXTENSIONS else "video"
        media_type = normalize_stock_media_type(media_type)
        end = clamp_stock_footage_end(edit.start, edit.end, media_type)

        # Prefer a clip already downloaded for this edit (e.g. previewed in the
        # Stock Footage tab) so the render matches what the user reviewed.
        if saved_path and Path(saved_path).exists():
            stock_footage_ranges.append(
                {"start": edit.start, "end": end, "footage_path": saved_path}
            )
            continue

        search_query = details.get("search_query")
        if not search_query:
            logger.warning("Skipping stock footage edit %s: no search_query", edit.id)
            continue
        try:
            cache_key = (media_type, search_query)
            if cache_key not in footage_by_query:
                footage_by_query[cache_key] = download_stock_media(
                    search_query, media_type=media_type, output_dir=str(OUTPUT_DIR)
                )
        except (ValueError, PexelsAPIError) as e:
            logger.warning("Skipping stock footage edit %s: %s", edit.id, e)
            continue
        stock_footage_ranges.append(
            {
                "start": edit.start,
                "end": end,
                "footage_path": footage_by_query[cache_key],
            }
        )

    # Render each diagram edit's graph spec to a transparent overlay video
    # (cached by spec hash, so unchanged diagrams render once). A failed or
    # invalid diagram is skipped (logged) rather than failing the whole render.
    diagram_ranges: list[dict[str, Any]] = []
    for edit in edits:
        if edit.type != "diagram":
            continue
        details = edit.details or {}
        try:
            background = _diagram_background(details.get("background"))
            spec = _diagram_spec(
                diagram_type=details.get("diagram_type", "flowchart"),
                title=details.get("title", ""),
                duration=edit.end - edit.start,
                graph=details.get("graph") or {},
                background=background,
                layout=details.get("layout", "landscape"),
            )
            # A solid background renders opaque (covers the frame); the
            # default renders with alpha so the video shows through.
            overlay_path, _ = get_or_render_overlay(
                spec,
                OUTPUT_DIR / "diagram_overlays",
                transparent=background is None,
                quality="medium",
            )
        except (ValueError, RuntimeError, subprocess.TimeoutExpired) as e:
            logger.warning("Skipping diagram edit %s: %s", edit.id, e)
            continue
        diagram_ranges.append(
            {"start": edit.start, "end": edit.end, "overlay_path": str(overlay_path)}
        )

    # A saved timeline (ordered, possibly rearranged segments) takes over as
    # the render's structure; cuts/zoom/stock still apply within its segments.
    timeline_rows = sorted(
        (edit for edit in edits if edit.type == TIMELINE_EDIT_TYPE),
        key=lambda row: (row.details or {}).get("position", 0),
    )

    captions_edits = [edit for edit in edits if edit.type == "captions"]
    text_caption_edits = [edit for edit in edits if edit.type == "text_caption"]
    # Both caption kinds burn in via libass as ffmpeg passes over the MoviePy
    # render; transcript captions first, then hand-written notes on top.
    has_burn_pass = bool(captions_edits or text_caption_edits)

    output_filename = f"rendered_{project_id}_{uuid.uuid4().hex[:8]}{video_path.suffix}"
    output_path = OUTPUT_DIR / output_filename
    # With a burn pass to follow, the MoviePy output is an intermediate file.
    render_target = (
        OUTPUT_DIR / f"precaption_{output_filename}" if has_burn_pass else output_path
    )

    # The MoviePy encode drives the progress bar. When a caption burn pass follows,
    # reserve the top slice of the bar for it so the user still sees movement while
    # ffmpeg re-encodes with the captions layered on.
    encode_scale = 0.9 if has_burn_pass else 1.0

    def on_progress(fraction: float) -> None:
        update_render_job(job_id, progress=round(fraction * encode_scale, 4))

    if timeline_rows:
        render_timeline(
            str(video_path),
            [{"start": row.start, "end": row.end} for row in timeline_rows],
            str(render_target),
            cut_ranges,
            zoom_ranges,
            stock_footage_ranges,
            diagram_ranges,
            on_progress=on_progress,
        )
    else:
        render_with_edits(
            str(video_path),
            cut_ranges,
            zoom_ranges,
            str(render_target),
            stock_footage_ranges,
            diagram_ranges,
            on_progress=on_progress,
        )

    # Chain the burn passes: each reads the previous stage's file and the last
    # one writes output_path (an intermediate in between when both run).
    burn_source = render_target
    if captions_edits:
        update_render_job(job_id, progress=encode_scale)
        caption_out = (
            OUTPUT_DIR / f"pretext_{output_filename}"
            if text_caption_edits
            else output_path
        )
        _burn_project_captions(
            video_path,
            burn_source,
            caption_out,
            captions_edits,
            cut_ranges,
            timeline_rows,
        )
        burn_source = caption_out
    if text_caption_edits:
        update_render_job(job_id, progress=encode_scale)
        _burn_project_text_captions(
            video_path,
            burn_source,
            output_path,
            text_caption_edits,
            cut_ranges,
            timeline_rows,
        )

    applied_edits = (
        len(cut_ranges)
        + len(zoom_ranges)
        + len(stock_footage_ranges)
        + len(diagram_ranges)
        + len(timeline_rows)
        + len(captions_edits)
        + len(text_caption_edits)
    )
    update_render_job(
        job_id,
        status="done",
        progress=1.0,
        output_url=f"/api/renders/{output_filename}",
        filename=output_filename,
        applied_edits=applied_edits,
    )
    logger.info("Render job %s completed (%s)", job_id, output_filename)


def _editing_plan_to_response(plan: EditingPlan) -> EditingPlanRecordResponse:
    """Convert a stored editing plan into its API response shape."""
    return EditingPlanRecordResponse(
        id=plan.id,
        project_id=plan.project_id,
        media_asset_id=plan.media_asset_id,
        plan=plan.plan or [],
        options=plan.options or {},
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


def _stock_footage_to_response(clip: StockFootage) -> StockFootageRecordResponse:
    """Convert a stored stock-footage clip into its API response shape."""
    return StockFootageRecordResponse(
        id=clip.id,
        project_id=clip.project_id,
        filename=clip.filename,
        path=clip.path,
        source=clip.source,
        query=clip.query,
        provider_id=clip.provider_id,
        duration=clip.duration,
        size=clip.size,
        created_at=clip.created_at,
    )


@app.put(
    "/api/projects/{project_id}/editing-plan",
    response_model=EditingPlanRecordResponse,
)
async def save_project_editing_plan(
    project_id: str,
    request: EditingPlanSaveRequest,
    session: Session = Depends(get_session),
):
    """Save (replace) the working editing plan for a project."""
    project = ensure_project(session, project_id)

    plan = get_latest_editing_plan(session, project_id)
    if plan is None:
        plan = EditingPlan(project_id=project_id)
        session.add(plan)
    plan.plan = request.plan
    plan.options = request.options
    plan.media_asset_id = request.media_asset_id
    plan.updated_at = utc_now()

    touch_project(session, project)
    session.commit()
    session.refresh(plan)
    return _editing_plan_to_response(plan)


@app.get(
    "/api/projects/{project_id}/editing-plan",
    response_model=EditingPlanRecordResponse,
)
async def get_project_editing_plan(
    project_id: str,
    session: Session = Depends(get_session),
):
    """Get the working editing plan for a project."""
    ensure_project(session, project_id)
    plan = get_latest_editing_plan(session, project_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="No editing plan saved")
    return _editing_plan_to_response(plan)


@app.get(
    "/api/projects/{project_id}/stock-footage",
    response_model=StockFootageListResponse,
)
async def list_project_stock_footage(
    project_id: str,
    session: Session = Depends(get_session),
):
    """List stock-footage clips registered for a project."""
    ensure_project(session, project_id)
    clips = get_stock_footage(session, project_id)
    return StockFootageListResponse(
        footage=[_stock_footage_to_response(clip) for clip in clips]
    )


@app.post(
    "/api/projects/{project_id}/stock-footage",
    response_model=StockFootageRecordResponse,
)
async def add_project_stock_footage(
    project_id: str,
    request: StockFootageCreate,
    session: Session = Depends(get_session),
):
    """Register a downloaded stock-footage clip with a project."""
    project = ensure_project(session, project_id)
    clip = StockFootage(
        project_id=project_id,
        filename=request.filename,
        path=request.path,
        source=request.source,
        query=request.query,
        provider_id=request.provider_id,
        duration=request.duration,
        size=request.size,
    )
    session.add(clip)
    touch_project(session, project)
    session.commit()
    session.refresh(clip)
    return _stock_footage_to_response(clip)


@app.get("/api/projects/{project_id}/export")
async def export_project(
    project_id: str,
    session: Session = Depends(get_session),
):
    """Export a project as a downloadable ``.vedit`` file.

    The file references source media by path; it does not embed the video.
    """
    ensure_project(session, project_id)
    try:
        document = build_project_file(session, project_id, resolve_media_path)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    payload = document.model_dump_json(indent=2)
    safe_name = (
        "".join(c if c.isalnum() or c in "-_ " else "_" for c in document.project.name)
        .strip()
        .replace(" ", "_")
        or "project"
    )
    filename = f"{safe_name}{PROJECT_FILE_EXTENSION}"
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/projects/import", response_model=ProjectImportResponse)
async def import_project(
    project_file: UploadFile = File(..., description="A .vedit project file"),
    session: Session = Depends(get_session),
):
    """Import a ``.vedit`` file, recreating the project and relinking media."""
    raw = await project_file.read()
    try:
        document = ProjectFile.model_validate_json(raw)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Invalid project file: {e}")

    try:
        result = load_project_file(
            session,
            document,
            upload_dir=UPLOAD_DIR,
            output_dir=OUTPUT_DIR,
        )
    except ProjectFileError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ProjectImportResponse(
        project_id=result.project_id,
        relinked=result.relinked,
        missing=[
            MissingMediaResponse(
                file_id=m.file_id,
                filename=m.filename,
                kind=m.kind,
                expected_abs=m.expected_abs,
                expected_rel=m.expected_rel,
            )
            for m in result.missing
        ],
        warnings=result.warnings,
    )


@app.post("/api/projects/{project_id}/relink", response_model=ProjectImportResponse)
async def relink_project_media(
    project_id: str,
    request: RelinkRequest,
    session: Session = Depends(get_session),
):
    """Relink a project's missing source media to new on-disk paths.

    For each ``file_id -> path`` entry, the file is copied into the upload dir
    under that file_id so the existing project resolves it. Unresolved entries
    are returned in ``missing``.
    """
    ensure_project(session, project_id)
    result = ProjectImportResponse(project_id=project_id)

    for file_id, new_path in request.media.items():
        asset = session.exec(
            select(MediaAsset).where(
                MediaAsset.project_id == project_id,
                MediaAsset.file_id == file_id,
            )
        ).first()
        if asset is None:
            result.warnings.append(f"No media asset {file_id} in this project")
            continue

        source = Path(new_path)
        if not source.exists():
            result.missing.append(
                MissingMediaResponse(
                    file_id=file_id,
                    filename=asset.filename,
                    kind="media",
                    expected_abs=new_path,
                )
            )
            continue

        dest = UPLOAD_DIR / f"{file_id}{source.suffix}"
        if source.resolve() != dest.resolve():
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
        result.relinked.append(file_id)

    return result


@app.get("/api/renders/{filename}")
async def get_rendered_video(filename: str):
    """Download a rendered video file."""
    output_path = OUTPUT_DIR / filename
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Rendered video not found")
    return file_response_for_video(output_path, filename)


# ============================================================================
# Captions Endpoints
# ============================================================================


@app.get("/api/captions/styles", response_model=CaptionStylesResponse)
async def list_caption_styles():
    """List the caption style presets available for burned-in captions."""
    return CaptionStylesResponse(
        styles=[
            CaptionStylePresetResponse(
                name=style.name,
                font_family=style.font_family,
                font_scale=style.font_scale,
                text_colour=style.text_colour,
                highlight_colour=style.highlight_colour,
                outline_colour=style.outline_colour,
                outline_scale=style.outline_scale,
                shadow_scale=style.shadow_scale,
                margin_v_scale=style.margin_v_scale,
                word_colours=list(style.word_colours),
                uppercase=style.uppercase,
                pop_scale=style.pop_scale,
                max_words_per_line=style.max_words_per_line,
            )
            for style in CAPTION_STYLE_PRESETS.values()
        ],
        default_style=DEFAULT_CAPTION_STYLE,
    )


# ============================================================================
# Caption Removal Endpoints
# ============================================================================


@app.post(
    "/api/video/remove-captions/{file_id}",
    response_model=CaptionRemovalStartResponse,
)
async def start_caption_removal(
    file_id: str,
    background_tasks: BackgroundTasks,
    mode: str = DEFAULT_MODE,
    use_gpu: Optional[bool] = None,
):
    """Start a background job that removes burned-in captions from a video.

    Detection and inpainting are handled by the external VideoSubtitleRemover tool. The
    job runs asynchronously; poll ``/api/caption-removal/status/{job_id}`` for the result.

    GPU usage defaults to the ``SUBTITLE_REMOVER_USE_GPU`` env var (CPU when unset). Pass
    ``?use_gpu=true`` / ``?use_gpu=false`` to override per request.
    """
    try:
        video_path = find_uploaded_video(file_id)
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))

    resolved_use_gpu = use_gpu_from_env() if use_gpu is None else use_gpu
    output_filename = f"nosub_{file_id}_{uuid.uuid4().hex[:8]}{video_path.suffix}"
    output_path = OUTPUT_DIR / output_filename

    job = create_job(file_id, output_filename)
    background_tasks.add_task(
        run_caption_removal_job,
        job.job_id,
        str(video_path),
        str(output_path),
        mode=mode,
        use_gpu=resolved_use_gpu,
    )
    logger.info(
        "Started caption removal job %s for file %s (mode=%s, gpu=%s)",
        job.job_id,
        file_id,
        mode,
        resolved_use_gpu,
    )

    return CaptionRemovalStartResponse(job_id=job.job_id, status=job.status)


@app.get(
    "/api/caption-removal/status/{job_id}",
    response_model=CaptionJobStatusResponse,
)
async def get_caption_removal_status(job_id: str):
    """Return the status (and result URL when done) of a caption removal job."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Caption removal job not found")

    output_url = f"/api/renders/{job.output_filename}" if job.status == "done" else None
    return CaptionJobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        output_url=output_url,
        error=job.error,
    )


# ============================================================================
# Gaming (Dota 2) Death-Detection Endpoints
# ============================================================================


def _encode_thumbnail(bgr) -> str:
    """Encode a BGR image array as a base64 PNG data URL."""
    import base64

    import cv2

    ok, buffer = cv2.imencode(".png", bgr)
    if not ok:
        return ""
    return "data:image/png;base64," + base64.b64encode(buffer.tobytes()).decode("ascii")


@app.get("/api/gaming/slot-preview/{file_id}", response_model=SlotPreviewResponse)
async def gaming_slot_preview(file_id: str, team: str = "radiant"):
    """Return the auto-identified player slot plus portrait thumbnails.

    Drives the manual slot selector: the client shows the five team portraits
    (auto pick highlighted) so the user can correct it before detecting deaths.
    """
    try:
        video_path = find_uploaded_video(file_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    try:
        auto_slot, confidence, thumbs = extract_slot_previews(
            str(video_path), team=team
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 - surface decode/HUD failures as 500
        logger.error("Slot preview failed for %s: %s", file_id, e)
        raise HTTPException(status_code=500, detail=str(e))

    return SlotPreviewResponse(
        team=team,
        auto_slot=auto_slot,
        confidence=confidence,
        slots=[_encode_thumbnail(thumb) for thumb in thumbs],
    )


@app.post(
    "/api/gaming/detect-deaths/{file_id}", response_model=DeathDetectStartResponse
)
async def start_death_detection(
    file_id: str,
    background_tasks: BackgroundTasks,
    team: str = "radiant",
    player_slot: Optional[int] = None,
    detect_kda: bool = False,
):
    """Start a background Dota 2 death-detection job over a recording.

    A single HUD scan detects the player's dead intervals and, when
    ``detect_kda`` is set (and tesseract is available), the kills/deaths/assists
    event markers for the play bar. ``detect_kda`` is off by default so plain
    death-cut detection stays fast; the "Detect K/D/A markers" action turns it on
    (the OCR pass roughly doubles the scan time). Auto-identifies the player's
    top-bar slot unless ``player_slot`` overrides it (the app's manual selector).
    Poll ``/api/gaming/death-detect/status/{job_id}`` for the intervals and
    markers.
    """
    try:
        video_path = find_uploaded_video(file_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    job = create_death_detect_job(file_id)
    background_tasks.add_task(
        run_death_detect_job,
        job.job_id,
        str(video_path),
        team=team,
        player_slot=player_slot,
        detect_kda=detect_kda,
    )
    logger.info(
        "Started death-detection job %s for file %s (team=%s, slot=%s)",
        job.job_id,
        file_id,
        team,
        player_slot,
    )
    return DeathDetectStartResponse(job_id=job.job_id, status=job.status)


@app.get(
    "/api/gaming/death-detect/status/{job_id}",
    response_model=DeathDetectStatusResponse,
)
async def get_death_detection_status(job_id: str):
    """Return the status and (when done) the detected dead intervals of a job."""
    job = get_death_detect_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Death detection job not found")

    return DeathDetectStatusResponse(
        job_id=job.job_id,
        status=job.status,
        intervals=[DeathIntervalResponse(**iv) for iv in job.intervals],
        events=[GamingEventResponse(**ev) for ev in job.events],
        player_slot=job.player_slot,
        confidence=job.confidence,
        kda_available=job.kda_available,
        error=job.error,
    )


@app.post(
    "/api/gaming/highlight-clip/{file_id}",
    response_model=HighlightClipStartResponse,
)
async def create_highlight_clip(
    file_id: str,
    request: HighlightClipRequest,
    background_tasks: BackgroundTasks,
):
    """Start a background job that trims a highlight clip between two timestamps.

    Re-encoding ``source[start:end]`` with ffmpeg scales with the clip length, so
    the work runs asynchronously instead of blocking the request. Poll
    ``GET /api/gaming/highlight-clip/status/{job_id}`` for the downloadable
    ``/api/renders`` URL once it is done.
    """
    if request.end <= request.start:
        raise HTTPException(status_code=400, detail="end must be greater than start")

    try:
        video_path = find_uploaded_video(file_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    output_filename = (
        f"highlight_{file_id}_{int(request.start)}-{int(request.end)}_"
        f"{uuid.uuid4().hex[:8]}.mp4"
    )
    output_path = OUTPUT_DIR / output_filename

    job = create_highlight_job(file_id)
    background_tasks.add_task(
        run_highlight_job,
        job.job_id,
        str(video_path),
        request.start,
        request.end,
        str(output_path),
        output_filename,
    )
    logger.info(
        "Started highlight job %s for file %s (%.2f-%.2fs)",
        job.job_id,
        file_id,
        request.start,
        request.end,
    )
    return HighlightClipStartResponse(job_id=job.job_id, status=job.status)


@app.get(
    "/api/gaming/highlight-clip/status/{job_id}",
    response_model=HighlightClipStatusResponse,
)
async def get_highlight_clip_status(job_id: str):
    """Return the status and (when done) the download URL of a highlight job."""
    job = get_highlight_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Highlight job not found")

    return HighlightClipStatusResponse(
        job_id=job.job_id,
        status=job.status,
        filename=job.filename,
        output_url=job.output_url,
        duration=job.duration,
        error=job.error,
    )


# ============================================================================
# YouTube Import Endpoints
# ============================================================================


@app.post(
    "/api/video/download-youtube",
    response_model=YouTubeDownloadStartResponse,
)
async def start_youtube_download(
    request: YouTubeDownloadRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    """Start a background job that imports a single video from YouTube.

    The video is downloaded into ``temp/uploads/`` under a generated ``file_id`` and, on
    completion, registered as a ``MediaAsset`` (creating a ``Project`` when none is given)
    exactly like a direct upload. The job runs asynchronously; poll
    ``/api/youtube-download/status/{job_id}`` for the result.

    Playlists, livestreams, and over-long videos are rejected by the worker.
    """
    if not request.url.strip():
        raise HTTPException(status_code=400, detail="No URL provided")

    # Validate an existing project up front so the client gets immediate feedback.
    if request.project_id and get_project(session, request.project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")

    file_id = str(uuid.uuid4())
    job = create_download_job(request.url)
    background_tasks.add_task(
        run_download_job,
        job.job_id,
        request.url,
        file_id,
        str(UPLOAD_DIR),
        project_id=request.project_id,
        project_name=request.project_name,
    )
    logger.info("Started YouTube download job %s for %s", job.job_id, request.url)

    return YouTubeDownloadStartResponse(job_id=job.job_id, status=job.status)


@app.get(
    "/api/youtube-download/status/{job_id}",
    response_model=YouTubeDownloadStatusResponse,
)
async def get_youtube_download_status(job_id: str):
    """Return the status (and resulting IDs when done) of a YouTube download job."""
    job = get_download_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="YouTube download job not found")

    return YouTubeDownloadStatusResponse(
        job_id=job.job_id,
        status=job.status,
        progress=job.progress,
        file_id=job.file_id,
        project_id=job.project_id,
        media_asset_id=job.media_asset_id,
        error=job.error,
    )


# ============================================================================
# System Endpoints
# ============================================================================


@app.get("/api/system/gpu", response_model=GpuDetectionResponse)
async def get_gpu_detection():
    """Detect NVIDIA GPUs on the host and whether the caption tool's venv can use them.

    ``available``/``gpus`` come from ``nvidia-smi`` (driver present on the host); ``tool``
    reflects ``torch.cuda.is_available()`` inside the tool's own virtualenv.
    """
    detection = detect_gpus()
    tool = detect_tool_cuda()
    return GpuDetectionResponse(**detection, tool=ToolCudaResponse(**tool))


# ============================================================================
# Transcript Endpoints
# ============================================================================


@app.post("/api/transcript/segments", response_model=TranscriptResponse)
async def extract_transcript_segments(
    video: UploadFile = File(..., description="Video file to transcribe"),
    model_size: str = Form(
        "base", description="Whisper model size (tiny, base, small, medium, large)"
    ),
):
    """
    Extract transcript from video as segments.

    Returns transcript divided into logical segments with timestamps.
    """
    if not video.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    # Save uploaded file
    video_path = temp_upload_path(video.filename)
    try:
        await save_upload_file(video, video_path)

        # Extract transcript
        logger.info(f"Extracting transcript segments from {video.filename}")
        segments = extract_transcript_as_segments(str(video_path), model_size)

        return TranscriptResponse(segments=segments)

    except Exception as e:
        logger.error(f"Error extracting transcript: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Clean up uploaded file
        if video_path.exists():
            video_path.unlink()


@app.get("/api/transcript/segments/{file_id}", response_model=TranscriptResponse)
async def extract_transcript_segments_by_id(
    file_id: str,
    model_size: str = "base",
):
    """Extract segment-level transcript from a previously uploaded video."""
    try:
        video_path = find_uploaded_video(file_id)
        logger.info(f"Extracting transcript segments from {video_path.name}")
        segments = extract_transcript_as_segments(str(video_path), model_size)
        return TranscriptResponse(segments=segments)
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error extracting transcript: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/transcript/sentences", response_model=TranscriptResponse)
async def extract_transcript_sentences_endpoint(
    video: UploadFile = File(..., description="Video file to transcribe"),
    model_size: str = Form(
        "base", description="Whisper model size (tiny, base, small, medium, large)"
    ),
):
    """
    Extract transcript from video as sentences.

    Returns transcript divided into sentences with timestamps.
    """
    if not video.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    # Save uploaded file
    video_path = temp_upload_path(video.filename)
    try:
        await save_upload_file(video, video_path)

        # Extract transcript
        logger.info(f"Extracting transcript sentences from {video.filename}")
        sentences = extract_transcript_as_sentences(str(video_path), model_size)

        return TranscriptResponse(segments=sentences)

    except Exception as e:
        logger.error(f"Error extracting transcript: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Clean up uploaded file
        if video_path.exists():
            video_path.unlink()


@app.get("/api/transcript/sentences/{file_id}", response_model=TranscriptResponse)
async def extract_transcript_sentences_by_id(
    file_id: str,
    model_size: str = "base",
):
    """Extract sentence-level transcript from a previously uploaded video."""
    try:
        video_path = find_uploaded_video(file_id)
        logger.info(f"Extracting transcript sentences from {video_path.name}")
        sentences = extract_transcript_as_sentences(str(video_path), model_size)
        return TranscriptResponse(segments=sentences)
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error extracting transcript: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/transcript/words", response_model=TranscriptWordsResponse)
async def extract_transcript_words_endpoint(
    video: UploadFile = File(..., description="Video file to transcribe"),
    model_size: str = Form(
        "base", description="Whisper model size (tiny, base, small, medium, large)"
    ),
):
    """
    Extract transcript from video as individual words.

    Returns word-level transcript with precise timestamps for each word.
    """
    if not video.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    # Save uploaded file
    video_path = temp_upload_path(video.filename)
    try:
        await save_upload_file(video, video_path)

        # Extract transcript
        logger.info(f"Extracting word-level transcript from {video.filename}")
        words = extract_transcript_as_words(str(video_path), model_size)

        return TranscriptWordsResponse(words=words)

    except Exception as e:
        logger.error(f"Error extracting transcript: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Clean up uploaded file
        if video_path.exists():
            video_path.unlink()


@app.get("/api/transcript/words/{file_id}", response_model=TranscriptWordsResponse)
async def extract_transcript_words_by_id(
    file_id: str,
    model_size: str = "base",
):
    """
    Extract word-level transcript from a previously uploaded video by file_id.

    Returns word-level transcript with precise timestamps for each word.
    """
    try:
        video_path = find_uploaded_video(file_id)
        logger.info(f"Extracting word-level transcript from {video_path.name}")
        words = extract_transcript_as_words(str(video_path), model_size)

        return TranscriptWordsResponse(words=words)
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error extracting transcript: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/api/transcript/words/{file_id}/start",
    response_model=TranscriptJobStartResponse,
)
async def start_transcript_job(
    file_id: str,
    background_tasks: BackgroundTasks,
    model_size: str = "base",
):
    """Start a background word-level transcription job over an uploaded video.

    Transcription is CPU-bound and can take minutes on a long recording, so it
    runs asynchronously instead of blocking the request. Poll
    ``GET /api/transcript/words/status/{job_id}`` for progress and, once done,
    the word-level transcript.
    """
    try:
        video_path = find_uploaded_video(file_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    job = create_transcript_job(file_id, model_size)
    background_tasks.add_task(
        run_transcript_job, job.job_id, str(video_path), model_size
    )
    logger.info(
        "Started transcription job %s for file %s (model=%s)",
        job.job_id,
        file_id,
        model_size,
    )
    return TranscriptJobStartResponse(job_id=job.job_id, status=job.status)


@app.get(
    "/api/transcript/words/status/{job_id}",
    response_model=TranscriptJobStatusResponse,
)
async def get_transcript_job_status(job_id: str):
    """Return the status, progress and (when done) words of a transcription job."""
    job = get_transcript_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Transcription job not found")

    return TranscriptJobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        progress=job.progress,
        words=[TranscriptWord(**word) for word in job.words],
        error=job.error,
    )


# ============================================================================
# Filler Words Endpoints
# ============================================================================


@app.post("/api/filler-words/detect", response_model=FillerWordsResponse)
async def detect_filler_words_endpoint(
    video: UploadFile = File(..., description="Video file to analyze"),
    model_size: str = Form(
        "base", description="Whisper model size (tiny, base, small, medium, large)"
    ),
):
    """
    Detect filler words (um, ah, uh, er, like, so, you know) in a video.

    Returns time ranges where filler words occur.
    """
    if not video.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    # Save uploaded file
    video_path = temp_upload_path(video.filename)
    try:
        await save_upload_file(video, video_path)

        # Extract word-level transcript
        logger.info(f"Extracting words from {video.filename}")
        words = extract_transcript_as_words(str(video_path), model_size)

        # Detect filler words
        logger.info("Detecting filler words")
        filler_word_ranges = detect_filler_words(words)

        return FillerWordsResponse(
            filler_word_ranges=filler_word_ranges, count=len(filler_word_ranges)
        )

    except Exception as e:
        logger.error(f"Error detecting filler words: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Clean up uploaded file
        if video_path.exists():
            video_path.unlink()


@app.get("/api/filler-words/detect/{file_id}", response_model=FillerWordsResponse)
async def detect_filler_words_by_id(
    file_id: str,
    model_size: str = "base",
):
    """Detect filler words in a previously uploaded video."""
    try:
        video_path = find_uploaded_video(file_id)
        logger.info(f"Extracting words from {video_path.name}")
        words = extract_transcript_as_words(str(video_path), model_size)

        logger.info("Detecting filler words")
        filler_word_ranges = detect_filler_words(words)

        return FillerWordsResponse(
            filler_word_ranges=filler_word_ranges,
            count=len(filler_word_ranges),
        )
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error detecting filler words: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Video Cutting Endpoints
# ============================================================================


@app.post("/api/video/cut-filler-words")
async def cut_filler_words_endpoint(
    video: UploadFile = File(..., description="Video file to edit"),
    model_size: str = Form(
        "base", description="Whisper model size (tiny, base, small, medium, large)"
    ),
):
    """
    Remove filler words from a video.

    Detects and removes filler words (um, ah, uh, er, like, so, you know)
    and returns the edited video file.
    """
    if not video.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    # Save uploaded file
    video_path = temp_upload_path(video.filename)
    output_filename = f"edited_{safe_download_name(video.filename)}"
    output_path = OUTPUT_DIR / output_filename

    try:
        await save_upload_file(video, video_path)

        # Extract word-level transcript
        logger.info(f"Extracting words from {video.filename}")
        words = extract_transcript_as_words(str(video_path), model_size)

        # Detect filler words
        logger.info("Detecting filler words")
        filler_word_ranges = detect_filler_words(words)

        # Cut filler words
        logger.info(f"Cutting {len(filler_word_ranges)} filler words from video")
        cut_filler_words(str(video_path), filler_word_ranges, str(output_path))

        return file_response_for_video(output_path, output_filename)

    except Exception as e:
        logger.error(f"Error cutting filler words: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Clean up uploaded file
        if video_path.exists():
            video_path.unlink()


@app.post("/api/video/cut-filler-words/{file_id}")
async def cut_filler_words_by_id(
    file_id: str,
    model_size: str = "base",
):
    """Remove filler words from a previously uploaded video."""
    try:
        video_path = find_uploaded_video(file_id)
        output_filename = f"edited_{file_id}{video_path.suffix}"
        output_path = OUTPUT_DIR / output_filename

        logger.info(f"Extracting words from {video_path.name}")
        words = extract_transcript_as_words(str(video_path), model_size)

        logger.info("Detecting filler words")
        filler_word_ranges = detect_filler_words(words)

        logger.info(f"Cutting {len(filler_word_ranges)} filler words from video")
        cut_filler_words(str(video_path), filler_word_ranges, str(output_path))

        return file_response_for_video(output_path, output_filename)
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error cutting filler words: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Editing Plan Endpoints
# ============================================================================


@app.post("/api/editing-plan/generate", response_model=EditingPlanResponse)
async def generate_editing_plan_endpoint(
    video: UploadFile = File(..., description="Video file to analyze"),
    model_size: str = Form(
        "base", description="Whisper model size (tiny, base, small, medium, large)"
    ),
    api_key: Optional[str] = Form(
        None,
        description="Groq API key (optional, uses API_KEY env var if not provided)",
    ),
    llm_model: str = Form(
        "llama-3.3-70b-versatile",
        description="Groq LLM model to use for editing plan generation",
    ),
    additional_context: str = Form(
        "", description="Additional context or instructions for editing"
    ),
):
    """
    Generate an AI-powered editing plan for a video.

    Analyzes the video transcript and generates suggestions for editing,
    including cuts, overlays, effects, and other enhancements.
    """
    if not video.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    # Save uploaded file
    video_path = temp_upload_path(video.filename)
    try:
        await save_upload_file(video, video_path)

        # Extract transcript
        logger.info(f"Extracting transcript from {video.filename}")
        transcript = extract_transcript_as_segments(str(video_path), model_size)

        # Generate editing plan
        logger.info("Generating editing plan")
        editing_plan = generate_editing_plan(
            transcript=transcript,
            api_key=api_key,
            model=llm_model,
            additional_context=additional_context,
        )

        return EditingPlanResponse(editing_plan=editing_plan)

    except Exception as e:
        logger.error(f"Error generating editing plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Clean up uploaded file
        if video_path.exists():
            video_path.unlink()


@app.post("/api/editing-plan/generate/{file_id}", response_model=EditingPlanResponse)
async def generate_editing_plan_by_id(
    file_id: str,
    request: EditingPlanRequest,
    session: Session = Depends(get_session),
):
    """Generate an AI-powered editing plan for a previously uploaded video.

    When the file belongs to a project, the generated plan is also saved to the
    project so it is captured in exports.
    """
    try:
        video_path = find_uploaded_video(file_id)
        logger.info(f"Extracting transcript from {video_path.name}")
        transcript = extract_transcript_as_segments(str(video_path), request.model_size)

        logger.info("Generating editing plan")
        editing_plan = generate_editing_plan(
            transcript=transcript,
            api_key=request.api_key,
            model=request.llm_model,
            additional_context=request.additional_context,
        )

        # Persist the plan to the owning project (best-effort) so it survives in
        # project exports and reloads.
        asset = session.exec(
            select(MediaAsset).where(MediaAsset.file_id == file_id)
        ).first()
        if asset is not None:
            project = get_project(session, asset.project_id)
            if project is not None:
                plan = get_latest_editing_plan(session, project.id)
                if plan is None:
                    plan = EditingPlan(project_id=project.id)
                    session.add(plan)
                plan.plan = editing_plan
                plan.options = {
                    "model_size": request.model_size,
                    "llm_model": request.llm_model,
                    "additional_context": request.additional_context,
                }
                plan.media_asset_id = asset.id
                plan.updated_at = utc_now()
                touch_project(session, project)
                session.commit()

        return EditingPlanResponse(editing_plan=editing_plan)
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error generating editing plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Diagram Suggestion Endpoints
# ============================================================================


DIAGRAM_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _diagram_background(value: Any) -> str | None:
    """Normalize a diagram edit's background choice.

    Args:
        value: The raw ``background`` value from the edit metadata — absent,
            ``"transparent"``, or a hex color like ``"#0f172a"``.

    Returns:
        str | None: A lowercase ``#rrggbb`` color, or None for transparent.

    Raises:
        ValueError: If the value is neither "transparent" nor a hex color.
    """
    if value is None or value == "" or value == "transparent":
        return None
    if isinstance(value, str) and DIAGRAM_HEX_COLOR_RE.match(value):
        return value.lower()
    raise ValueError(
        f"diagram background must be 'transparent' or a #rrggbb color, got {value!r}"
    )


def _diagram_spec(
    diagram_type: str,
    title: str,
    duration: float,
    graph: dict,
    background: str | None = None,
    layout: str = "landscape",
) -> dict:
    """Build a validated, render-ready diagram spec.

    Args:
        diagram_type: One of the supported diagram types.
        title: Short on-screen title.
        duration: Overlay duration in seconds (the edit's end - start).
        graph: Raw graph dict (nodes/edges/reveal_order).
        background: Solid background color (``#rrggbb``), or None for the
            default (transparent overlay at final render, dark preview).
        layout: Frame orientation, "landscape" or "portrait" (unknown values
            fall back to landscape).

    Returns:
        dict: Spec consumed by the Manim scene template.

    Raises:
        ValueError: If the duration is unusable or the graph fails validation.
    """
    if duration <= 0:
        raise ValueError("diagram duration must be positive")
    validated = validate_graph(graph)
    # Reveal offsets are relative to the segment start; keep them inside the
    # segment (leaving a beat at the end so the last node is visible).
    for node in validated["nodes"]:
        if "reveal_at" in node:
            node["reveal_at"] = min(node["reveal_at"], max(0.0, duration - 1.0))
    spec = {
        "diagram_type": diagram_type,
        "title": title or "",
        "duration": duration,
        "layout": normalize_layout(layout),
        "graph": validated,
    }
    if background:
        spec["background"] = background
    return spec


@app.post("/api/diagrams/render", response_model=DiagramRenderResponse)
def render_diagram_preview(request: DiagramRenderRequest):
    """Render one diagram spec to a browser-playable preview video.

    Uses Manim in a subprocess to produce a low-quality .mp4 on a dark
    background (the final project render uses a transparent overlay instead).
    Results are cached by spec hash, so re-rendering an unchanged diagram is
    instant. Runs synchronously in FastAPI's threadpool — a small diagram
    takes on the order of seconds to render.
    """
    try:
        spec = _diagram_spec(
            diagram_type=request.diagram_type,
            title=request.title,
            duration=request.end - request.start,
            graph=request.graph,
            background=_diagram_background(request.background),
            layout=request.layout,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        # Previews live directly in OUTPUT_DIR so the existing
        # /api/renders/{filename} route can serve them.
        output_path, cached = get_or_render_overlay(
            spec, OUTPUT_DIR, transparent=False, quality="low"
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Diagram render timed out")
    except RuntimeError as e:
        logger.error(f"Error rendering diagram preview: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return DiagramRenderResponse(
        video_url=f"/api/renders/{output_path.name}",
        filename=output_path.name,
        cached=cached,
    )


@app.post("/api/diagrams/suggest/{file_id}", response_model=DiagramSuggestResponse)
async def suggest_diagrams_by_id(
    file_id: str,
    request: DiagramSuggestRequest,
):
    """Suggest animated diagram overlays for a previously uploaded video.

    Analyzes the sentence-level transcript and returns segments where the
    speaker describes a process, timeline, comparison, or cycle, each with a
    validated graph spec (nodes, edges, reveal order) ready for rendering.
    """
    try:
        video_path = find_uploaded_video(file_id)
        logger.info(f"Extracting transcript sentences from {video_path.name}")
        transcript = extract_transcript_as_sentences(
            str(video_path), request.model_size
        )

        logger.info("Suggesting diagram overlays")
        diagrams = suggest_diagrams(
            transcript=transcript,
            api_key=request.api_key,
            model=request.llm_model,
            additional_context=request.additional_context,
        )

        return DiagramSuggestResponse(diagrams=diagrams)
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        logger.error(f"Invalid diagram suggestion request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error suggesting diagrams: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Project Assistant Chat Endpoints
# ============================================================================


def _describe_edit_details(edit: EditOperation) -> str:
    """Render the human-relevant bits of an edit's details for the LLM."""
    details = edit.details or {}
    parts = []
    if edit.type == "zoom" and details.get("zoom_level"):
        parts.append(f"zoom level {details['zoom_level']}")
    if edit.type == "insert_stock_footage":
        if details.get("search_query"):
            parts.append(f"query '{details['search_query']}'")
        if details.get("media_type") == "image":
            parts.append("still image")
    if edit.type == "diagram":
        if details.get("diagram_type"):
            parts.append(details["diagram_type"])
        if details.get("title"):
            parts.append(f"'{details['title']}'")
        if details.get("layout") == "portrait":
            parts.append("portrait")
    return f" ({', '.join(parts)})" if parts else ""


def _project_chat_summary(session: Session, project: Project) -> str:
    """Build a text description of a project's media, edits, and timeline."""
    lines = [f"Project: {project.name} (id {project.id})"]

    assets = session.exec(
        select(MediaAsset).where(MediaAsset.project_id == project.id)
    ).all()
    if assets:
        lines.append("Source media:")
        for asset in assets:
            duration = (
                f"{asset.duration:.1f}s"
                if asset.duration is not None
                else "unknown duration"
            )
            lines.append(f"- {asset.filename} ({duration})")
    else:
        lines.append("Source media: none uploaded.")

    edits = session.exec(
        select(EditOperation)
        .where(EditOperation.project_id == project.id)
        .where(EditOperation.type != TIMELINE_EDIT_TYPE)
        .order_by(EditOperation.start)
    ).all()
    if edits:
        lines.append(f"Saved edit operations ({len(edits)}):")
        for edit in edits:
            state = "enabled" if edit.enabled else "disabled"
            lines.append(
                f"- [id {edit.id}] {edit.type} {edit.start:.1f}s-{edit.end:.1f}s,"
                f" {state}, from {edit.source}{_describe_edit_details(edit)}"
            )
    else:
        lines.append("Saved edit operations: none yet.")

    timeline_rows = _timeline_segment_rows(session, project.id)
    if timeline_rows:
        ranges = ", ".join(f"{row.start:.1f}s-{row.end:.1f}s" for row in timeline_rows)
        lines.append(
            f"Custom timeline: {len(timeline_rows)} segments in playback order: {ranges}."
        )
    else:
        lines.append("Custom timeline: none saved (video plays in original order).")

    return "\n".join(lines)


@app.post("/api/projects/{project_id}/chat", response_model=ProjectChatResponse)
async def project_chat(
    project_id: str,
    request: ProjectChatRequest,
    session: Session = Depends(get_session),
):
    """Answer a chat message about the current project, acting on it if asked.

    Builds a description of the project's media, saved edits, and timeline from
    the database, combines it with the transcript and recent editor activity
    sent by the client, and runs the assistant agent. The agent may invoke
    tools (add/update/delete edits, silence detection) before replying; the
    executed actions are returned so the client can log them and refresh. The
    chat itself is not persisted.
    """
    project = ensure_project(session, project_id)

    project_context = build_project_context(
        project_summary=_project_chat_summary(session, project),
        activity_log=request.activity_log,
        transcript_text=request.transcript,
    )

    # Tool execution context: the project's primary source video, when present.
    media_asset = session.exec(
        select(MediaAsset)
        .where(MediaAsset.project_id == project.id)
        .order_by(MediaAsset.created_at)
    ).first()
    video_path = None
    if media_asset is not None:
        try:
            video_path = find_uploaded_video(media_asset.file_id)
        except FileNotFoundError:
            video_path = None
    tool_context = ToolContext(
        session=session,
        project=project,
        media_asset=media_asset,
        video_path=video_path,
    )

    try:
        result = generate_chat_reply(
            messages=[message.model_dump() for message in request.messages],
            project_context=project_context,
            tool_context=tool_context,
            api_key=request.api_key,
            model=request.llm_model,
        )
        return ProjectChatResponse(
            reply=result.reply,
            actions=[
                ChatActionResponse(
                    tool=action.tool, summary=action.summary, ok=action.ok
                )
                for action in result.actions
            ],
            edits_changed=result.edits_changed,
        )
    except ValueError as e:
        logger.error(f"Invalid chat request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error generating chat reply: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Stock Footage Endpoints
# ============================================================================


@app.post("/api/stock-footage/download", response_model=StockFootageResponse)
async def download_stock_footage_endpoint(
    search_term: str = Form(
        ..., description="Search term for stock footage (e.g., 'ocean waves')"
    ),
    quality: str = Form("hd", description="Video quality (hd, sd, or original)"),
    media_type: str = Form(
        "video", description="B-roll media type ('video' or 'image')"
    ),
):
    """
    Download stock B-roll from Pexels based on search term.

    Searches Pexels API and downloads a random matching video clip or,
    when media_type is 'image', a random matching still photo.
    Requires PEXELS_API_KEY environment variable.
    """
    media_type = normalize_stock_media_type(media_type)
    try:
        logger.info(f"Downloading stock {media_type} for '{search_term}'")
        if media_type == "image":
            file_path = download_stock_media(
                search_term, media_type="image", output_dir=str(OUTPUT_DIR)
            )
        else:
            file_path = download_stock_footage(
                search_term=search_term,
                output_dir=str(OUTPUT_DIR),
                quality=quality,
            )

        return StockFootageResponse(
            file_path=file_path,
            search_term=search_term,
            media_type=media_type,
        )

    except Exception as e:
        logger.error(f"Error downloading stock footage: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stock-footage/download/{filename}")
async def get_stock_footage_file(filename: str):
    """
    Download a previously fetched stock footage file.

    Returns the video or image file for download.
    """
    file_path = OUTPUT_DIR / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    guessed_type, _ = mimetypes.guess_type(filename)

    return FileResponse(
        path=file_path,
        media_type=guessed_type or "video/mp4",
        filename=filename,
    )


# ============================================================================
# Landing Page
# ============================================================================

LANDING_PAGE_PATH = Path(__file__).parent / "static" / "landing_page.html"


@app.get("/landing_page", include_in_schema=False)
async def landing_page() -> FileResponse:
    """Serve the public marketing landing page."""
    if not LANDING_PAGE_PATH.exists():
        raise HTTPException(status_code=404, detail="Landing page not found")
    return FileResponse(LANDING_PAGE_PATH, media_type="text/html")


# ============================================================================
# Health Check
# ============================================================================


@app.get("/")
async def root():
    """Root endpoint - API information."""
    return {
        "name": "Video Editor API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "transcript_segments": "/api/transcript/segments",
            "transcript_sentences": "/api/transcript/sentences",
            "transcript_words": "/api/transcript/words",
            "detect_filler_words": "/api/filler-words/detect",
            "cut_filler_words": "/api/video/cut-filler-words",
            "generate_editing_plan": "/api/editing-plan/generate",
            "download_stock_footage": "/api/stock-footage/download",
        },
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}
