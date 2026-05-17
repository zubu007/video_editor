"""FastAPI application for video editing operations."""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import FastAPI, File, HTTPException, UploadFile, Form
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.features.transcript.extract import (
    extract_transcript_as_segments,
    extract_transcript_as_sentences,
    extract_transcript_as_words,
)
from backend.features.filler_words.detect import detect_filler_words
from backend.features.video_cutter.cut import cut_filler_words
from backend.features.editing_plan.generator import generate_editing_plan
from backend.features.pexels.download import download_stock_footage
from backend.features.audio.extract import get_waveform_data_from_file_id

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Video Editor API",
    description="API for automated video editing operations including transcript extraction, filler word removal, and editing plan generation",
    version="1.0.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:3000"],  # Vite and CRA dev servers
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create temp directories for uploads and outputs
UPLOAD_DIR = Path("temp/uploads")
OUTPUT_DIR = Path("temp/outputs")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


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


class WaveformResponse(BaseModel):
    """Response model for waveform data."""
    waveform: list[float] = Field(..., description="Array of peak amplitude values (0.0 to 1.0)")
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


# ============================================================================
# Video Upload/Serving Endpoints
# ============================================================================

@app.post("/api/video/upload", response_model=VideoUploadResponse)
async def upload_video(
    video: UploadFile = File(..., description="Video file to upload"),
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
        
        return VideoUploadResponse(
            file_id=file_id,
            file_url=f"/api/video/{file_id}",
            filename=video.filename,
            size=file_size,
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
    # Find the video file (check all common extensions)
    video_path = None
    for ext in ['.mp4', '.webm', '.mov', '.avi', '.mkv']:
        candidate = UPLOAD_DIR / f"{file_id}{ext}"
        if candidate.exists():
            video_path = candidate
            break
    
    if not video_path or not video_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    
    # Return video file with appropriate content type
    content_type_map = {
        '.mp4': 'video/mp4',
        '.webm': 'video/webm',
        '.mov': 'video/quicktime',
        '.avi': 'video/x-msvideo',
        '.mkv': 'video/x-matroska',
    }
    
    content_type = content_type_map.get(video_path.suffix, 'video/mp4')
    
    return FileResponse(
        path=video_path,
        media_type=content_type,
        filename=video_path.name,
    )


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


# ============================================================================
# Transcript Endpoints
# ============================================================================

@app.post("/api/transcript/segments", response_model=TranscriptResponse)
async def extract_transcript_segments(
    video: UploadFile = File(..., description="Video file to transcribe"),
    model_size: str = Form("base", description="Whisper model size (tiny, base, small, medium, large)"),
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


@app.post("/api/transcript/sentences", response_model=TranscriptResponse)
async def extract_transcript_sentences_endpoint(
    video: UploadFile = File(..., description="Video file to transcribe"),
    model_size: str = Form("base", description="Whisper model size (tiny, base, small, medium, large)"),
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


@app.post("/api/transcript/words", response_model=TranscriptWordsResponse)
async def extract_transcript_words_endpoint(
    video: UploadFile = File(..., description="Video file to transcribe"),
    model_size: str = Form("base", description="Whisper model size (tiny, base, small, medium, large)"),
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
    # Find the video file (check all common extensions)
    video_path = None
    for ext in ['.mp4', '.webm', '.mov', '.avi', '.mkv']:
        candidate = UPLOAD_DIR / f"{file_id}{ext}"
        if candidate.exists():
            video_path = candidate
            break
    
    if not video_path or not video_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    
    try:
        # Extract transcript
        logger.info(f"Extracting word-level transcript from {video_path.name}")
        words = extract_transcript_as_words(str(video_path), model_size)
        
        return TranscriptWordsResponse(words=words)
    
    except Exception as e:
        logger.error(f"Error extracting transcript: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Filler Words Endpoints
# ============================================================================

@app.post("/api/filler-words/detect", response_model=FillerWordsResponse)
async def detect_filler_words_endpoint(
    video: UploadFile = File(..., description="Video file to analyze"),
    model_size: str = Form("base", description="Whisper model size (tiny, base, small, medium, large)"),
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
        logger.info(f"Detecting filler words")
        filler_word_ranges = detect_filler_words(words)
        
        return FillerWordsResponse(
            filler_word_ranges=filler_word_ranges,
            count=len(filler_word_ranges)
        )
    
    except Exception as e:
        logger.error(f"Error detecting filler words: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        # Clean up uploaded file
        if video_path.exists():
            video_path.unlink()


# ============================================================================
# Video Cutting Endpoints
# ============================================================================

@app.post("/api/video/cut-filler-words")
async def cut_filler_words_endpoint(
    video: UploadFile = File(..., description="Video file to edit"),
    model_size: str = Form("base", description="Whisper model size (tiny, base, small, medium, large)"),
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
        logger.info(f"Detecting filler words")
        filler_word_ranges = detect_filler_words(words)
        
        # Cut filler words
        logger.info(f"Cutting {len(filler_word_ranges)} filler words from video")
        cut_filler_words(str(video_path), filler_word_ranges, str(output_path))
        
        # Return the edited video
        return FileResponse(
            path=output_path,
            media_type="video/mp4",
            filename=output_filename,
        )
    
    except Exception as e:
        logger.error(f"Error cutting filler words: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        # Clean up uploaded file
        if video_path.exists():
            video_path.unlink()


# ============================================================================
# Editing Plan Endpoints
# ============================================================================

@app.post("/api/editing-plan/generate", response_model=EditingPlanResponse)
async def generate_editing_plan_endpoint(
    video: UploadFile = File(..., description="Video file to analyze"),
    model_size: str = Form("base", description="Whisper model size (tiny, base, small, medium, large)"),
    api_key: Optional[str] = Form(None, description="OpenAI API key (optional, uses env var if not provided)"),
    llm_model: str = Form("gpt-4", description="LLM model to use for editing plan generation"),
    additional_context: str = Form("", description="Additional context or instructions for editing"),
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
        logger.info(f"Generating editing plan")
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


# ============================================================================
# Stock Footage Endpoints
# ============================================================================

@app.post("/api/stock-footage/download", response_model=StockFootageResponse)
async def download_stock_footage_endpoint(
    search_term: str = Form(..., description="Search term for stock footage (e.g., 'ocean waves')"),
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
