"""Serialize a stored project into a portable ``ProjectFile`` document."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, Optional

from sqlmodel import Session, select

from backend.features.project_io.paths import fingerprint_file, relative_to_cwd
from backend.features.project_io.schema import (
    EditRef,
    MediaRef,
    PlanRef,
    ProjectFile,
    ProjectMeta,
    StockRef,
)
from backend.storage.database import (
    EditOperation,
    MediaAsset,
    Project,
    get_latest_editing_plan,
    get_stock_footage,
    utc_now,
)


# A callable that maps a file_id to its on-disk path (or None if unresolved).
# Injected so this module need not know the app's upload-dir lookup rules.
MediaPathResolver = Callable[[str], Optional[Path]]


def _media_ref(asset: MediaAsset, resolve: MediaPathResolver) -> MediaRef:
    """Build a ``MediaRef`` for a media asset, fingerprinting it if on disk."""
    path = resolve(asset.file_id)
    extension = path.suffix if path else Path(asset.filename).suffix
    return MediaRef(
        file_id=asset.file_id,
        filename=asset.filename,
        extension=extension,
        duration=asset.duration,
        size=asset.size,
        path_abs=str(path.resolve()) if path else None,
        path_rel=relative_to_cwd(path) if path else None,
        fingerprint=fingerprint_file(path) if path else fingerprint_file(Path()),
    )


def build_project_file(
    session: Session,
    project_id: str,
    media_path_resolver: MediaPathResolver,
) -> ProjectFile:
    """Assemble the full ``.vedit`` document for a project.

    Args:
        session: Active database session.
        project_id: Project to export.
        media_path_resolver: Maps a ``file_id`` to its current on-disk path, or
            ``None`` if the source file can no longer be found.

    Returns:
        A populated :class:`ProjectFile`.

    Raises:
        ValueError: If the project does not exist.
    """
    project = session.get(Project, project_id)
    if project is None:
        raise ValueError(f"Project not found: {project_id}")

    assets: Iterable[MediaAsset] = session.exec(
        select(MediaAsset)
        .where(MediaAsset.project_id == project_id)
        .order_by(MediaAsset.created_at)
    ).all()
    media = [_media_ref(asset, media_path_resolver) for asset in assets]
    file_id_by_asset_id = {asset.id: asset.file_id for asset in assets}

    edits = session.exec(
        select(EditOperation)
        .where(EditOperation.project_id == project_id)
        .order_by(EditOperation.start, EditOperation.created_at)
    ).all()
    edit_refs = [
        EditRef(
            type=edit.type,
            source=edit.source,
            start=edit.start,
            end=edit.end,
            enabled=edit.enabled,
            media_file_id=file_id_by_asset_id.get(edit.media_asset_id),
            details=edit.details or {},
        )
        for edit in edits
    ]

    stock_refs = []
    for clip in get_stock_footage(session, project_id):
        path = Path(clip.path)
        stock_refs.append(
            StockRef(
                filename=clip.filename,
                path_abs=str(path.resolve()) if path.exists() else clip.path,
                path_rel=relative_to_cwd(path) if path.exists() else None,
                source=clip.source,
                query=clip.query,
                provider_id=clip.provider_id,
                duration=clip.duration,
                size=clip.size,
                fingerprint=fingerprint_file(path),
            )
        )

    plan_ref = None
    saved_plan = get_latest_editing_plan(session, project_id)
    if saved_plan is not None:
        plan_ref = PlanRef(
            plan=saved_plan.plan or [],
            options=saved_plan.options or {},
            media_file_id=file_id_by_asset_id.get(saved_plan.media_asset_id),
        )

    return ProjectFile(
        saved_at=utc_now(),
        source_project_id=project.id,
        project=ProjectMeta(
            id=project.id,
            name=project.name,
            created_at=project.created_at,
            updated_at=project.updated_at,
        ),
        media=media,
        stock_footage=stock_refs,
        edits=edit_refs,
        editing_plan=plan_ref,
    )
