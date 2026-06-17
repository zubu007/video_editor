"""SQLite storage for projects, media assets, and edit operations."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import Column, JSON
from sqlmodel import Field, Session, SQLModel, create_engine, select

DATA_DIR = Path("data")
DATABASE_PATH = DATA_DIR / "video_editor.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


def utc_now() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(timezone.utc)


class Project(SQLModel, table=True):
    """A video editing project."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MediaAsset(SQLModel, table=True):
    """A source media file uploaded for a project."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    file_id: str = Field(index=True, unique=True)
    filename: str
    file_url: str
    size: int
    duration: float | None = None
    created_at: datetime = Field(default_factory=utc_now)


class EditOperation(SQLModel, table=True):
    """A non-destructive edit operation recorded for a project."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    media_asset_id: str | None = Field(default=None, foreign_key="mediaasset.id")
    type: str = Field(index=True)
    source: str = Field(index=True)
    start: float
    end: float
    enabled: bool = True
    details: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


def init_db() -> None:
    """Create database tables."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    """Yield a database session for FastAPI dependencies."""
    with Session(engine) as session:
        yield session


def get_project(session: Session, project_id: str) -> Project | None:
    """Fetch a project by ID."""
    return session.get(Project, project_id)


def get_media_asset_by_file_id(session: Session, file_id: str) -> MediaAsset | None:
    """Fetch a media asset by uploaded file ID."""
    statement = select(MediaAsset).where(MediaAsset.file_id == file_id)
    return session.exec(statement).first()


def touch_project(session: Session, project: Project) -> None:
    """Update a project's modification timestamp."""
    project.updated_at = utc_now()
    session.add(project)
