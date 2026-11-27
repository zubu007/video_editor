"""API routes for Ranking Shorts."""

from __future__ import annotations

import io
import logging
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ValidationError
from sqlalchemy.engine import Engine
from sqlmodel import Session

from backend.features.ranking import jobs, store
from backend.features.ranking.compose import render_overlay
from backend.features.ranking.download import (
    DownloadCancelled,
    DownloadError,
    cleanup_partials,
    download_clip,
    safe_display_name,
    validate_source_url,
)
from backend.features.ranking.media import MAX_SOURCE_BYTES
from backend.features.ranking.render import (
    RenderCancelled,
    RenderError,
    export_issues,
    render_composition,
)
from backend.features.ranking.schema import RankingDocument
from backend.features.ranking.timeline import build_schedule
from backend.storage.database import Project, get_project, get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ranking", tags=["ranking"])

# At most two concurrent downloads across the whole server.
_DOWNLOAD_SLOTS = threading.BoundedSemaphore(2)
UPLOAD_CHUNK = 1024 * 1024


class CreateProjectRequest(BaseModel):
    """Body for creating a ranking project."""

    name: str | None = None


class SaveRequest(BaseModel):
    """Body for saving a composition."""

    revision: int
    document: dict[str, Any]
    name: str | None = None


class DownloadRequest(BaseModel):
    """Body for importing one clip from a link."""

    url: str


class RenderRequest(BaseModel):
    """Body for starting a render."""

    revision: int | None = None


class OverlayRequest(BaseModel):
    """Body for rasterising the overlay of a (draft) document."""

    document: dict[str, Any]
    active_index: int = 0


def _ensure_ranking_project(session: Session, project_id: str) -> Project:
    project = get_project(session, project_id)
    if project is None or project.project_type != "ranking":
        raise HTTPException(404, "Ranking project not found")
    return project


def _payload(session: Session, project: Project) -> dict[str, Any]:
    doc = store.load_document(session, project.id)
    if doc is None:
        raise HTTPException(404, "Ranking composition not found")
    media = {c.id: store.clip_media(session, c.asset_id) for c in doc.clips}
    issues = [i.to_dict() for i in export_issues(session, doc)]
    try:
        schedule = build_schedule(doc)
        timeline: dict[str, Any] | None = {
            "total_frames": schedule.total_frames,
            "total_seconds": schedule.total_seconds,
            "segments": [
                {"clip_id": s.clip_id, "start_frame": s.start_frame, "frames": s.frames}
                for s in schedule.segments
            ],
        }
    except ValueError:
        timeline = None
    return {
        "project": {"id": project.id, "name": project.name},
        "revision": doc.revision,
        "document": doc.model_dump(mode="json"),
        "media": media,
        "issues": issues,
        "timeline": timeline,
        "jobs": [j.to_dict() for j in jobs.jobs_for_project(project.id)],
    }


@router.post("/projects")
def create_project(
    body: CreateProjectRequest | None = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Create an empty ranking project with five blank slots."""
    project = store.create_ranking_project(session, body.name if body else None)
    return _payload(session, project)


@router.get("/projects/{project_id}")
def get_ranking_project(
    project_id: str, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Return the composition, media availability and current jobs."""
    return _payload(session, _ensure_ranking_project(session, project_id))


@router.put("/projects/{project_id}")
def save_ranking_project(
    project_id: str,
    body: SaveRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Validate and save the composition against an expected revision."""
    project = _ensure_ranking_project(session, project_id)
    try:
        store.save_document(session, project_id, body.document, body.revision)
    except store.RevisionConflict as exc:
        raise HTTPException(
            409,
            detail={"message": str(exc), "current_revision": exc.current},
        ) from exc
    except ValidationError as exc:
        raise HTTPException(422, detail=_validation_message(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    if body.name and body.name.strip() and body.name != project.name:
        project.name = body.name.strip()[:120]
        session.add(project)
        session.commit()
        session.refresh(project)
    return _payload(session, project)


def _validation_message(exc: ValidationError) -> str:
    first = exc.errors()[0]
    where = ".".join(str(part) for part in first["loc"])
    return f"{where}: {first['msg']}" if where else first["msg"]


@router.post("/overlay")
def draft_overlay(body: OverlayRequest) -> Response:
    """Rasterise the overlay for a draft document at a playback position."""
    try:
        doc = RankingDocument.model_validate(body.document)
    except ValidationError as exc:
        raise HTTPException(422, detail=_validation_message(exc)) from exc
    ordered = doc.in_playback_order()
    index = max(0, min(body.active_index, len(ordered) - 1))
    image = render_overlay(doc, [c.id for c in ordered[: index + 1]], ordered[index].id)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return Response(buffer.getvalue(), media_type="image/png")


# --------------------------------------------------------------------------- imports


def _current_clip(session: Session, project_id: str, clip_id: str):
    doc = store.load_document(session, project_id)
    clip = next((c for c in doc.clips if c.id == clip_id), None) if doc else None
    if clip is None:
        raise HTTPException(404, "Clip not found")
    return clip


def _run_download(
    bind: Engine, job_id: str, project_id: str, clip: Any, url: str
) -> None:
    job = jobs.get_job(job_id)
    if job is None:
        return
    file_id = uuid.uuid4().hex
    with _DOWNLOAD_SLOTS:
        if job.cancel_event.is_set():
            return
        jobs.update_job(job_id, status="running", phase="Downloading")
        try:
            result = download_clip(
                url,
                store.UPLOAD_DIR,
                file_id,
                job.cancel_event,
                lambda fraction: jobs.update_job(job_id, progress=fraction * 0.9),
            )
        except DownloadCancelled:
            return
        except (ValueError, DownloadError) as exc:
            jobs.update_job(job_id, status="error", phase="Failed", error=str(exc))
            return
        except Exception as exc:
            logger.exception("Ranking download %s failed", job_id)
            jobs.update_job(
                job_id, status="error", phase="Failed", error=f"Download failed: {exc}"
            )
            return

    jobs.update_job(job_id, phase="Processing", progress=0.95)
    try:
        attached = store.attach_source(
            bind,
            project_id,
            clip.id,
            job.generation,
            file_id,
            f"{result['title'] or 'clip'}.mp4",
            result["title"],
        )
    except ValueError as exc:
        cleanup_partials(store.UPLOAD_DIR, file_id)
        jobs.update_job(job_id, status="error", phase="Failed", error=str(exc))
        return
    except Exception as exc:
        logger.exception("Ranking attach %s failed", job_id)
        cleanup_partials(store.UPLOAD_DIR, file_id)
        jobs.update_job(job_id, status="error", phase="Failed", error=str(exc))
        return
    if not attached:
        jobs.update_job(
            job_id,
            status="cancelled",
            phase="Cancelled",
            error="The slot changed while downloading; the file was discarded.",
        )
        return
    jobs.update_job(job_id, status="done", phase="Ready", progress=1.0)


@router.post("/projects/{project_id}/clips/{clip_id}/download")
def start_clip_download(
    project_id: str,
    clip_id: str,
    body: DownloadRequest,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Start importing one clip from a YouTube/Instagram link."""
    _ensure_ranking_project(session, project_id)
    clip = _current_clip(session, project_id, clip_id)
    try:
        validate_source_url(body.url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    jobs.cancel_jobs(project_id, clip_id)
    job = jobs.create_job(
        "download", project_id, clip_id=clip_id, generation=clip.source_generation
    )
    background.add_task(
        _run_download,
        session.get_bind(),
        job.job_id,
        project_id,
        clip,
        body.url.strip(),
    )
    return job.to_dict()


@router.post("/projects/{project_id}/clips/{clip_id}/upload")
def upload_clip(
    project_id: str,
    clip_id: str,
    video: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Attach an uploaded video to a clip slot after validating it."""
    project = _ensure_ranking_project(session, project_id)
    clip = _current_clip(session, project_id, clip_id)
    suffix = Path(video.filename or "").suffix.lower()
    if suffix not in store.VIDEO_EXTENSIONS:
        raise HTTPException(
            400, f"Unsupported file type; use one of {store.VIDEO_EXTENSIONS}"
        )

    jobs.cancel_jobs(project_id, clip_id)
    store.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4().hex
    destination = store.UPLOAD_DIR / f"{file_id}{suffix}"
    written = 0
    try:
        with destination.open("wb") as handle:
            while chunk := video.file.read(UPLOAD_CHUNK):
                written += len(chunk)
                if written > MAX_SOURCE_BYTES:
                    raise HTTPException(
                        413, f"File exceeds the {MAX_SOURCE_BYTES // 1024**2} MB limit"
                    )
                handle.write(chunk)
        attached = store.attach_source(
            session.get_bind(),
            project_id,
            clip_id,
            clip.source_generation,
            file_id,
            safe_display_name(video.filename or "clip.mp4"),
            Path(video.filename or "").stem,
        )
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    except ValueError as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(400, str(exc)) from exc
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    if not attached:
        raise HTTPException(409, "The slot changed during upload; try again.")
    session.expire_all()
    return _payload(session, project)


# ----------------------------------------------------------------------------- jobs


@router.get("/jobs/{job_id}")
def get_job_status(job_id: str) -> dict[str, Any]:
    """Return a job's status."""
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job.to_dict()


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    """Request cancellation of a job."""
    job = jobs.cancel_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job.to_dict()


def _run_render(
    bind: Engine,
    job_id: str,
    doc: RankingDocument,
    output_path: Path,
    preview: bool,
) -> None:
    jobs.update_job(job_id, status="running", phase="Preparing")
    try:
        render_composition(bind, doc, job_id, output_path, preview=preview)
    except RenderCancelled:
        jobs.update_job(job_id, status="cancelled", phase="Cancelled")
        return
    except RenderError as exc:
        jobs.update_job(job_id, status="error", phase="Failed", error=str(exc))
        return
    except Exception as exc:
        logger.exception("Ranking render %s failed", job_id)
        jobs.update_job(job_id, status="error", phase="Failed", error=str(exc))
        return

    with Session(bind) as session:
        exists = get_project(session, doc.project_id) is not None
    job = jobs.get_job(job_id)
    if not exists or (job and job.cancel_event.is_set()):
        output_path.unlink(missing_ok=True)
        jobs.update_job(job_id, status="cancelled", phase="Cancelled")
        return
    jobs.update_job(
        job_id,
        status="done",
        phase="Done",
        progress=1.0,
        result={
            "output_url": f"/api/renders/{output_path.name}",
            "filename": output_path.name,
            "revision": doc.revision,
            "duration": build_schedule(doc).total_seconds,
        },
    )


def _start_render(
    project_id: str,
    body: RenderRequest,
    background: BackgroundTasks,
    session: Session,
    preview: bool,
) -> dict[str, Any]:
    _ensure_ranking_project(session, project_id)
    doc = store.load_document(session, project_id)
    assert doc is not None
    if body.revision is not None and body.revision != doc.revision:
        raise HTTPException(
            409,
            detail={
                "message": "The saved revision changed; save and retry.",
                "current_revision": doc.revision,
            },
        )
    issues = export_issues(session, doc)
    if issues:
        raise HTTPException(
            422,
            detail={
                "message": issues[0].message,
                "issues": [i.to_dict() for i in issues],
            },
        )
    if jobs.active_render(project_id) is not None:
        raise HTTPException(409, "A render is already running for this project.")
    kind = "preview" if preview else "render"
    job = jobs.create_job(kind, project_id, revision=doc.revision)
    name = f"ranking_{project_id}_r{doc.revision}_{kind}_{job.job_id[:8]}.mp4"
    background.add_task(
        _run_render,
        session.get_bind(),
        job.job_id,
        doc,
        store.OUTPUT_DIR / name,
        preview,
    )
    return job.to_dict()


@router.post("/projects/{project_id}/preview")
def start_preview(
    project_id: str,
    background: BackgroundTasks,
    body: RenderRequest | None = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Render a reduced-resolution draft of the saved revision."""
    return _start_render(project_id, body or RenderRequest(), background, session, True)


@router.post("/projects/{project_id}/render")
def start_render(
    project_id: str,
    background: BackgroundTasks,
    body: RenderRequest | None = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Validate and freeze the saved revision, then render the final video."""
    return _start_render(
        project_id, body or RenderRequest(), background, session, False
    )
