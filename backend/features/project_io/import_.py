"""Recreate a project from a ``.vedit`` document, relinking referenced media."""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from backend.features.project_io.paths import (
    fingerprint_matches,
    resolve_reference,
)
from backend.features.project_io.schema import (
    PROJECT_FILE_FORMAT,
    PROJECT_FILE_VERSION,
    MediaRef,
    ProjectFile,
    StockRef,
)
from backend.storage.database import (
    EditOperation,
    EditingPlan,
    MediaAsset,
    Project,
    StockFootage,
)


@dataclass
class MissingMedia:
    """A media or footage reference that could not be resolved on this machine."""

    file_id: str | None
    filename: str
    kind: str  # "media" | "stock_footage"
    expected_abs: str | None
    expected_rel: str | None


@dataclass
class ImportResult:
    """Outcome of loading a project file."""

    project_id: str
    relinked: list[str] = field(default_factory=list)
    missing: list[MissingMedia] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ProjectFileError(ValueError):
    """Raised when a project file is malformed or unsupported."""


def validate_document(doc: ProjectFile) -> None:
    """Validate the document's format magic and version. Raise on mismatch."""
    if doc.format != PROJECT_FILE_FORMAT:
        raise ProjectFileError(
            f"Not a video-editor project file (format={doc.format!r})"
        )
    if doc.version > PROJECT_FILE_VERSION:
        raise ProjectFileError(
            f"Project file version {doc.version} is newer than supported "
            f"version {PROJECT_FILE_VERSION}; please update the app."
        )


def _existing_file_ids(session: Session) -> set[str]:
    """Return the set of file_ids already used by media assets."""
    return set(session.exec(select(MediaAsset.file_id)).all())


def _materialize_media(
    ref: MediaRef,
    upload_dir: Path,
    used_file_ids: set[str],
    result: ImportResult,
) -> tuple[str, MediaAsset | None]:
    """Resolve a media reference to an upload-dir file, copying if needed.

    Returns the (possibly new) file_id and a created ``MediaAsset`` row. If the
    source file cannot be found, records it in ``result.missing`` and still
    creates the asset (so the project loads and can be relinked later).
    """
    resolved = resolve_reference(ref.path_abs, ref.path_rel)
    if resolved is None:
        # Last resort: a file already sitting in the upload dir under this id.
        candidate = upload_dir / f"{ref.file_id}{ref.extension}"
        if candidate.exists():
            resolved = candidate

    # Pick a collision-free file_id; reuse the original when free so an
    # already-present upload file is found without copying.
    file_id = ref.file_id
    if file_id in used_file_ids:
        file_id = uuid.uuid4().hex
    used_file_ids.add(file_id)

    dest = upload_dir / f"{file_id}{ref.extension}"

    if resolved is not None:
        if not fingerprint_matches(resolved, ref.fingerprint):
            result.warnings.append(
                f"{ref.filename}: file content differs from when the project "
                "was saved (size changed)."
            )
        if resolved.resolve() != dest.resolve():
            upload_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(resolved, dest)
        result.relinked.append(file_id)
    else:
        result.missing.append(
            MissingMedia(
                file_id=ref.file_id,
                filename=ref.filename,
                kind="media",
                expected_abs=ref.path_abs,
                expected_rel=ref.path_rel,
            )
        )

    asset = MediaAsset(
        project_id="",  # set by caller once the project id is known
        file_id=file_id,
        filename=ref.filename,
        file_url=f"/api/video/{file_id}",
        size=ref.size or 0,
        duration=ref.duration,
    )
    return file_id, asset


def _materialize_stock(
    ref: StockRef,
    output_dir: Path,
    result: ImportResult,
) -> StockFootage:
    """Resolve a stock-footage reference, falling back to the output dir."""
    resolved = resolve_reference(ref.path_abs, ref.path_rel)
    if resolved is None:
        candidate = output_dir / ref.filename
        if candidate.exists():
            resolved = candidate

    if resolved is None:
        result.missing.append(
            MissingMedia(
                file_id=None,
                filename=ref.filename,
                kind="stock_footage",
                expected_abs=ref.path_abs,
                expected_rel=ref.path_rel,
            )
        )
        path = ref.path_abs or str(output_dir / ref.filename)
    else:
        path = str(resolved.resolve())

    return StockFootage(
        project_id="",
        filename=ref.filename,
        path=path,
        source=ref.source,
        query=ref.query,
        provider_id=ref.provider_id,
        duration=ref.duration,
        size=ref.size,
    )


def _rewrite_footage_path(details: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    """Point an edit's ``footage_path`` at a resolvable file when possible."""
    footage_path = details.get("footage_path")
    if not footage_path:
        return details
    if Path(footage_path).exists():
        return details
    fallback = output_dir / Path(footage_path).name
    if fallback.exists():
        details = {**details, "footage_path": str(fallback.resolve())}
    return details


def load_project_file(
    session: Session,
    doc: ProjectFile,
    *,
    upload_dir: Path,
    output_dir: Path,
) -> ImportResult:
    """Recreate a project (with a fresh id) from a parsed project file.

    Media is relinked by path; files that cannot be found are reported in the
    result's ``missing`` list rather than aborting the import.
    """
    validate_document(doc)

    project = Project(name=doc.project.name)
    session.add(project)
    result = ImportResult(project_id=project.id)

    used_file_ids = _existing_file_ids(session)
    asset_by_old_file_id: dict[str, MediaAsset] = {}

    for ref in doc.media:
        _, asset = _materialize_media(ref, upload_dir, used_file_ids, result)
        asset.project_id = project.id
        session.add(asset)
        asset_by_old_file_id[ref.file_id] = asset

    session.flush()  # assign asset ids before referencing them

    for clip in doc.stock_footage:
        row = _materialize_stock(clip, output_dir, result)
        row.project_id = project.id
        session.add(row)

    for edit in doc.edits:
        asset = (
            asset_by_old_file_id.get(edit.media_file_id)
            if edit.media_file_id
            else None
        )
        session.add(
            EditOperation(
                project_id=project.id,
                media_asset_id=asset.id if asset else None,
                type=edit.type,
                source=edit.source,
                start=edit.start,
                end=edit.end,
                enabled=edit.enabled,
                details=_rewrite_footage_path(edit.details or {}, output_dir),
            )
        )

    if doc.editing_plan is not None:
        plan_asset = (
            asset_by_old_file_id.get(doc.editing_plan.media_file_id)
            if doc.editing_plan.media_file_id
            else None
        )
        session.add(
            EditingPlan(
                project_id=project.id,
                media_asset_id=plan_asset.id if plan_asset else None,
                plan=doc.editing_plan.plan or [],
                options=doc.editing_plan.options or {},
            )
        )

    session.commit()
    return result
