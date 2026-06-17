"""FastAPI application for video editing operations."""

from __future__ import annotations

import logging
import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import aiofiles
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
from backend.features.editing_plan.generator import generate_editing_plan
from backend.features.filler_words.detect import detect_filler_words
from backend.features.pexels.download import PexelsAPIError, download_stock_footage
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
from backend.features.video_cutter.cut import cut_filler_words, render_with_edits
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
# Edit operation types that can be persisted and rendered for a project.
SUPPORTED_EDIT_TYPES = {"cut", "zoom", "insert_stock_footage"}
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


class FillerWordsResponse(BaseModel):
    """Response model for filler word detection."""

    filler_word_ranges: list[FillerWordRange] = []
    count: int = Field(..., description="Number of filler words detected")


class EditingPlanResponse(BaseModel):
    """Response model for editing plan generation."""

    editing_plan: list[EditingDecision] = []


class StockFootageResponse(BaseModel):
    """Response model for stock footage download."""

    file_path: str = Field(..., description="Path to downloaded video file")
    search_term: str = Field(..., description="Search term used")


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
    """Save an uploaded file to disk."""
    async with aiofiles.open(destination, "wb") as f:
        content = await upload_file.read()
        await f.write(content)


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

        # Get file size
        file_size = video_path.stat().st_size
        duration = get_video_duration(video_path)
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
):
    """Detect silence/pause ranges for a previously uploaded video."""
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

        return AudioPausesResponse(
            pauses=pauses,
            count=len(pauses),
            total_silence_duration=get_total_silence_duration(pauses),
            settings={
                "min_silence_duration": min_silence_duration,
                "silence_threshold": silence_threshold,
                "seek_step": seek_step,
                "merge_gap": merge_gap,
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


@app.post("/api/projects/{project_id}/render", response_model=RenderResponse)
async def render_project(
    project_id: str,
    session: Session = Depends(get_session),
):
    """Render a project by applying enabled cut edits."""
    ensure_project(session, project_id)

    media_asset = session.exec(
        select(MediaAsset)
        .where(MediaAsset.project_id == project_id)
        .order_by(MediaAsset.created_at)
    ).first()
    if not media_asset:
        raise HTTPException(status_code=404, detail="Project has no media asset")

    try:
        video_path = find_uploaded_video(media_asset.file_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    edits = session.exec(
        select(EditOperation)
        .where(
            EditOperation.project_id == project_id,
            EditOperation.enabled == True,  # noqa: E712
        )
        .order_by(EditOperation.start)
    ).all()

    cut_ranges = [
        {"start": edit.start, "end": edit.end}
        for edit in edits
        if edit.type == "cut"
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
    # caching downloads per query so repeated queries hit Pexels once. A failed
    # download is skipped (logged) rather than failing the whole render.
    stock_footage_ranges: list[dict[str, Any]] = []
    footage_by_query: dict[str, str] = {}
    for edit in edits:
        if edit.type != "insert_stock_footage":
            continue
        details = edit.details or {}

        # Prefer a clip already downloaded for this edit (e.g. previewed in the
        # Stock Footage tab) so the render matches what the user reviewed.
        saved_path = details.get("footage_path")
        if saved_path and Path(saved_path).exists():
            stock_footage_ranges.append(
                {"start": edit.start, "end": edit.end, "footage_path": saved_path}
            )
            continue

        search_query = details.get("search_query")
        if not search_query:
            logger.warning("Skipping stock footage edit %s: no search_query", edit.id)
            continue
        try:
            if search_query not in footage_by_query:
                footage_by_query[search_query] = download_stock_footage(
                    search_query, output_dir=str(OUTPUT_DIR)
                )
        except (ValueError, PexelsAPIError) as e:
            logger.warning("Skipping stock footage edit %s: %s", edit.id, e)
            continue
        stock_footage_ranges.append(
            {
                "start": edit.start,
                "end": edit.end,
                "footage_path": footage_by_query[search_query],
            }
        )

    output_filename = f"rendered_{project_id}_{uuid.uuid4().hex[:8]}{video_path.suffix}"
    output_path = OUTPUT_DIR / output_filename

    try:
        render_with_edits(
            str(video_path),
            cut_ranges,
            zoom_ranges,
            str(output_path),
            stock_footage_ranges,
        )
    except Exception as e:
        logger.error(f"Error rendering project: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return RenderResponse(
        output_url=f"/api/renders/{output_filename}",
        filename=output_filename,
        applied_edits=len(cut_ranges) + len(zoom_ranges) + len(stock_footage_ranges),
    )


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

    output_url = (
        f"/api/renders/{job.output_filename}" if job.status == "done" else None
    )
    return CaptionJobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        output_url=output_url,
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
    video_path = UPLOAD_DIR / video.filename
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
    video_path = UPLOAD_DIR / video.filename
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
    video_path = UPLOAD_DIR / video.filename
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
    video_path = UPLOAD_DIR / video.filename
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
    video_path = UPLOAD_DIR / video.filename
    output_filename = f"edited_{video.filename}"
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
        None, description="Groq API key (optional, uses API_KEY env var if not provided)"
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
    video_path = UPLOAD_DIR / video.filename
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
# Stock Footage Endpoints
# ============================================================================


@app.post("/api/stock-footage/download", response_model=StockFootageResponse)
async def download_stock_footage_endpoint(
    search_term: str = Form(
        ..., description="Search term for stock footage (e.g., 'ocean waves')"
    ),
    quality: str = Form("hd", description="Video quality (hd, sd, or original)"),
):
    """
    Download stock footage from Pexels based on search term.

    Searches Pexels API and downloads a random matching video.
    Requires PEXELS_API_KEY environment variable.
    """
    try:
        logger.info(f"Downloading stock footage for '{search_term}'")
        file_path = download_stock_footage(
            search_term=search_term,
            output_dir=str(OUTPUT_DIR),
            quality=quality,
        )

        return StockFootageResponse(
            file_path=file_path,
            search_term=search_term,
        )

    except Exception as e:
        logger.error(f"Error downloading stock footage: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stock-footage/download/{filename}")
async def get_stock_footage_file(filename: str):
    """
    Download a previously fetched stock footage file.

    Returns the video file for download.
    """
    file_path = OUTPUT_DIR / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=file_path,
        media_type="video/mp4",
        filename=filename,
    )


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
