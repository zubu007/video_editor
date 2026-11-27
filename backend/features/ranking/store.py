"""Persistence for ranking compositions and their owned media assets."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from backend.features.ranking import jobs
from backend.features.ranking.media import probe_media
from backend.features.ranking.schema import (
    RankingDocument,
    default_document,
    merge_client_document,
)
from backend.storage.database import (
    MediaAsset,
    Project,
    RankingComposition,
    touch_project,
    utc_now,
)

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path("temp/uploads")
OUTPUT_DIR = Path("temp/outputs")
VIDEO_EXTENSIONS = (".mp4", ".webm", ".mov", ".avi", ".mkv")

# Serialises read-modify-write of compositions between request and worker threads.
LOCK = threading.RLock()


class RevisionConflict(Exception):
    """The client saved against an out-of-date revision."""

    def __init__(self, current: int) -> None:
        super().__init__(f"Revision conflict (current revision {current})")
        self.current = current


def find_media_path(file_id: str) -> Path | None:
    """Resolve a stored asset's file on disk."""
    for ext in VIDEO_EXTENSIONS:
        candidate = UPLOAD_DIR / f"{file_id}{ext}"
        if candidate.exists():
            return candidate
    return None


def create_ranking_project(session: Session, name: str | None = None) -> Project:
    """Create a ranking project with an empty five-slot composition."""
    project = Project(name=name or "Ranking short", project_type="ranking")
    session.add(project)
    session.flush()
    doc = default_document(project.id)
    session.add(
        RankingComposition(
            project_id=project.id,
            schema_version=doc.schema_version,
            revision=doc.revision,
            document=doc.model_dump(mode="json"),
        )
    )
    session.commit()
    session.refresh(project)
    return project


def _row(session: Session, project_id: str) -> RankingComposition | None:
    return session.exec(
        select(RankingComposition).where(RankingComposition.project_id == project_id)
    ).first()


def load_document(session: Session, project_id: str) -> RankingDocument | None:
    """Return the stored composition (revision taken from the row)."""
    row = _row(session, project_id)
    if row is None:
        return None
    doc = RankingDocument.model_validate(row.document)
    doc.revision = row.revision
    return doc


def _write(
    session: Session,
    row: RankingComposition,
    doc: RankingDocument,
    *,
    bump: bool = True,
) -> None:
    """Persist ``doc``; server-side attaches keep the revision so they never cause
    spurious 409s for a client with pending edits."""
    if bump:
        row.revision += 1
    doc.revision = row.revision
    row.document = doc.model_dump(mode="json")
    row.updated_at = utc_now()
    session.add(row)
    project = session.get(Project, row.project_id)
    if project is not None:
        touch_project(session, project)
    session.commit()


def delete_asset(session: Session, asset_id: str | None) -> None:
    """Delete an asset row and its file."""
    if not asset_id:
        return
    asset = session.get(MediaAsset, asset_id)
    if asset is None:
        return
    path = find_media_path(asset.file_id)
    if path is not None:
        path.unlink(missing_ok=True)
    session.delete(asset)


def save_document(
    session: Session, project_id: str, incoming: dict[str, Any], expected_revision: int
) -> RankingDocument:
    """Validate and store a client document.

    Raises:
        LookupError: If the project has no composition.
        RevisionConflict: If ``expected_revision`` is stale.
        ValueError: If the document is invalid.
    """
    with LOCK:
        row = _row(session, project_id)
        if row is None:
            raise LookupError("Ranking project not found")
        if row.revision != expected_revision:
            raise RevisionConflict(row.revision)
        stored = RankingDocument.model_validate(row.document)
        doc = merge_client_document(stored, incoming)

        kept = {c.id for c in doc.clips}
        removed = [c for c in stored.clips if c.id not in kept]
        for clip in removed:
            jobs.cancel_jobs(project_id, clip.id)
            delete_asset(session, clip.asset_id)
        _write(session, row, doc)
        return doc


def attach_source(
    bind: Engine,
    project_id: str,
    clip_id: str,
    generation: int,
    file_id: str,
    filename: str,
    suggested_name: str | None,
) -> bool:
    """Attach a finished source file to a clip slot if the slot is still current.

    Returns ``False`` (and removes the file) when the project, clip or generation no
    longer matches, so stale jobs can never attach.
    """
    path = find_media_path(file_id)
    try:
        if path is None:
            return False
        info = probe_media(path)
        with LOCK, Session(bind) as session:
            row = _row(session, project_id)
            if row is None or session.get(Project, project_id) is None:
                path.unlink(missing_ok=True)
                return False
            doc = RankingDocument.model_validate(row.document)
            clip = next((c for c in doc.clips if c.id == clip_id), None)
            if clip is None or clip.source_generation != generation:
                path.unlink(missing_ok=True)
                return False
            asset = MediaAsset(
                project_id=project_id,
                file_id=file_id,
                filename=filename,
                file_url=f"/api/video/{file_id}",
                size=path.stat().st_size,
                duration=info.duration,
            )
            session.add(asset)
            session.flush()
            delete_asset(session, clip.asset_id)
            clip.asset_id = asset.id
            clip.media = info
            clip.source_generation = generation + 1
            clip.trim_in = 0.0
            clip.trim_out = None
            clip.fit = "fill"
            clip.focal_x = clip.focal_y = 0.5
            clip.zoom = 1.0
            if suggested_name and not clip.name.strip():
                clip.name = suggested_name[:120]
            _write(session, row, doc, bump=False)
            return True
    except Exception:
        if path is not None:
            path.unlink(missing_ok=True)
        raise


def clip_media(session: Session, clip_asset_id: str | None) -> dict[str, Any]:
    """Return availability details for a clip's attached asset."""
    if not clip_asset_id:
        return {"available": False, "reason": "empty"}
    asset = session.get(MediaAsset, clip_asset_id)
    if asset is None:
        return {"available": False, "reason": "missing"}
    if find_media_path(asset.file_id) is None:
        return {"available": False, "reason": "missing", "file_id": asset.file_id}
    return {
        "available": True,
        "file_id": asset.file_id,
        "file_url": asset.file_url,
        "filename": asset.filename,
    }


def missing_source_count(session: Session, project_id: str) -> tuple[int, int]:
    """Return ``(clip_count, clips_without_available_media)``."""
    doc = load_document(session, project_id)
    if doc is None:
        return 0, 0
    missing = sum(
        1 for c in doc.clips if not clip_media(session, c.asset_id)["available"]
    )
    return len(doc.clips), missing


def delete_project_data(session: Session, project_id: str) -> int:
    """Cancel jobs and remove the composition and renders of a project.

    Asset rows/files are removed by the generic project deletion.

    Returns:
        The number of render files removed.
    """
    jobs.cancel_jobs(project_id)
    with LOCK:
        row = _row(session, project_id)
        if row is not None:
            session.delete(row)
    removed = 0
    for path in OUTPUT_DIR.glob(f"ranking_{project_id}_*"):
        path.unlink(missing_ok=True)
        removed += 1
    return removed
