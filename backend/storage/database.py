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
    # "standard" or "gaming" — decides which editor tabs the frontend shows
    # when the project is reopened (gaming adds Deaths/Highlights).
    project_type: str = Field(default="standard")
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


class EditingPlan(SQLModel, table=True):
    """A generated AI editing plan saved for a project.

    Stores the LLM-produced list of editing decisions plus the options used to
    generate it. A project may keep several plans; the most recent one is the
    working plan.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    media_asset_id: str | None = Field(default=None, foreign_key="mediaasset.id")
    plan: list[Any] = Field(default_factory=list, sa_column=Column(JSON))
    options: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class StockFootage(SQLModel, table=True):
    """A stock-footage clip downloaded for a project.

    Tracks B-roll pulled from Pexels (or similar) so a project's footage can be
    saved/restored. The file itself lives under ``temp/outputs/``; ``path`` is the
    on-disk location referenced by render and project files.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    filename: str
    path: str
    source: str = "pexels"
    query: str | None = None
    provider_id: str | None = None
    duration: float | None = None
    size: int | None = None
    created_at: datetime = Field(default_factory=utc_now)


def init_db() -> None:
    """Create database tables and apply lightweight migrations."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)
    _migrate_columns()


def _migrate_columns() -> None:
    """Add columns that ``create_all`` cannot add to pre-existing tables."""
    from sqlalchemy import text

    with engine.connect() as connection:
        columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(project)"))
        }
        if "project_type" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE project ADD COLUMN project_type TEXT "
                    "NOT NULL DEFAULT 'standard'"
                )
            )
            connection.commit()


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


def get_latest_editing_plan(session: Session, project_id: str) -> EditingPlan | None:
    """Return the most recently updated editing plan for a project, if any."""
    statement = (
        select(EditingPlan)
        .where(EditingPlan.project_id == project_id)
        .order_by(EditingPlan.updated_at.desc())
    )
    return session.exec(statement).first()


def get_stock_footage(session: Session, project_id: str) -> list[StockFootage]:
    """Return all stock-footage clips registered for a project."""
    statement = (
        select(StockFootage)
        .where(StockFootage.project_id == project_id)
        .order_by(StockFootage.created_at)
    )
    return list(session.exec(statement).all())
