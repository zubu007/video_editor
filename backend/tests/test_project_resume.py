"""Tests for project saving/loading: list, open (resume), and delete."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from backend.app import app
from backend.storage.database import EditOperation, MediaAsset, Project, get_session

UPLOADS = Path("temp/uploads")


def create_test_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app), engine


def seed_project(
    engine,
    name: str = "My Game",
    project_type: str = "gaming",
    file_id: str = "resume-test",
    with_edit: bool = True,
) -> str:
    """Create a project with one media asset (and optionally one edit)."""
    with Session(engine) as session:
        project = Project(name=name, project_type=project_type)
        session.add(project)
        session.commit()
        session.refresh(project)
        asset = MediaAsset(
            project_id=project.id,
            file_id=file_id,
            filename="game.mp4",
            file_url=f"/api/video/{file_id}",
            size=1234,
            duration=120.5,
        )
        session.add(asset)
        if with_edit:
            session.add(
                EditOperation(
                    project_id=project.id,
                    type="cut",
                    source="death_detection",
                    start=10.0,
                    end=15.0,
                )
            )
        session.commit()
        return project.id


def fake_upload(file_id: str) -> Path:
    path = UPLOADS / f"{file_id}.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake video")
    return path


def test_list_projects_reports_media_type_and_availability():
    client, engine = create_test_client()
    video_path = fake_upload("resume-list")
    try:
        project_id = seed_project(engine, file_id="resume-list")
        seed_project(
            engine,
            name="No Source",
            project_type="standard",
            file_id="resume-missing",
            with_edit=False,
        )

        response = client.get("/api/projects")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 2
        by_name = {p["name"]: p for p in body["projects"]}

        available = by_name["My Game"]
        assert available["id"] == project_id
        assert available["project_type"] == "gaming"
        assert available["file_id"] == "resume-list"
        assert available["filename"] == "game.mp4"
        assert available["duration"] == 120.5
        assert available["source_available"] is True
        assert available["edit_count"] == 1

        missing = by_name["No Source"]
        assert missing["source_available"] is False
        assert missing["edit_count"] == 0
    finally:
        video_path.unlink(missing_ok=True)
        app.dependency_overrides.clear()


def test_open_project_returns_upload_shaped_payload():
    client, engine = create_test_client()
    video_path = fake_upload("resume-open")
    try:
        project_id = seed_project(engine, file_id="resume-open")

        response = client.get(f"/api/projects/{project_id}/open")
        assert response.status_code == 200
        body = response.json()
        assert body["file_id"] == "resume-open"
        assert body["project_id"] == project_id
        assert body["filename"] == "game.mp4"
        assert body["duration"] == 120.5
        assert body["project_type"] == "gaming"
        assert body["name"] == "My Game"
        assert body["media_asset_id"]
    finally:
        video_path.unlink(missing_ok=True)
        app.dependency_overrides.clear()


def test_open_project_410_when_source_file_is_gone():
    client, engine = create_test_client()
    try:
        project_id = seed_project(engine, file_id="resume-gone")
        response = client.get(f"/api/projects/{project_id}/open")
        assert response.status_code == 410
        assert "no longer on disk" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_open_project_404_without_media_or_project():
    client, engine = create_test_client()
    try:
        with Session(engine) as session:
            project = Project(name="Empty")
            session.add(project)
            session.commit()
            session.refresh(project)
            empty_id = project.id

        assert client.get(f"/api/projects/{empty_id}/open").status_code == 404
        assert client.get("/api/projects/nope/open").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_delete_project_removes_rows_and_files():
    client, engine = create_test_client()
    video_path = fake_upload("resume-delete")
    try:
        project_id = seed_project(engine, file_id="resume-delete")

        response = client.delete(f"/api/projects/{project_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["deleted_edits"] == 1
        assert body["deleted_assets"] == 1
        assert body["deleted_files"] == ["resume-delete.mp4"]
        assert not video_path.exists()

        assert client.get(f"/api/projects/{project_id}").status_code == 404
        assert client.get("/api/projects").json()["count"] == 0
    finally:
        video_path.unlink(missing_ok=True)
        app.dependency_overrides.clear()


def test_delete_project_can_keep_files():
    client, engine = create_test_client()
    video_path = fake_upload("resume-keep")
    try:
        project_id = seed_project(engine, file_id="resume-keep")

        response = client.delete(
            f"/api/projects/{project_id}", params={"delete_files": "false"}
        )
        assert response.status_code == 200
        assert response.json()["deleted_files"] == []
        assert video_path.exists()
    finally:
        video_path.unlink(missing_ok=True)
        app.dependency_overrides.clear()


def test_upload_rejected_when_disk_is_low():
    """The middleware refuses uploads that would exhaust the disk (507)."""
    import collections
    from unittest.mock import patch

    client, _ = create_test_client()
    usage = collections.namedtuple("usage", "total used free")
    try:
        with patch(
            "backend.app.shutil.disk_usage",
            return_value=usage(total=100 * 1024**3, used=99 * 1024**3, free=1024**3),
        ):
            response = client.post(
                "/api/video/upload",
                files={"video": ("game.mp4", b"x" * 1024, "video/mp4")},
            )
        assert response.status_code == 507
        assert "disk space" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_upload_persists_project_type(tmp_path):
    client, engine = create_test_client()
    stored: list[Path] = []
    try:
        from unittest.mock import patch

        def fake_duration(path):
            return 33.0

        with (
            patch("backend.app.get_video_duration", side_effect=fake_duration),
            patch("backend.app.ensure_constant_frame_rate", side_effect=lambda p: p),
        ):
            response = client.post(
                "/api/video/upload",
                files={"video": ("game.mp4", b"fake bytes", "video/mp4")},
                data={"project_type": "gaming"},
            )
        assert response.status_code == 200
        file_id = response.json()["file_id"]
        stored.append(UPLOADS / f"{file_id}.mp4")

        project_id = response.json()["project_id"]
        project = client.get(f"/api/projects/{project_id}").json()
        assert project["project_type"] == "gaming"

        bad = client.post(
            "/api/video/upload",
            files={"video": ("game.mp4", b"fake bytes", "video/mp4")},
            data={"project_type": "sports"},
        )
        assert bad.status_code == 400
    finally:
        for path in stored:
            path.unlink(missing_ok=True)
        app.dependency_overrides.clear()
