from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from backend.app import app
from backend.storage.database import MediaAsset, Project, get_session


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


def test_create_update_delete_project_edits():
    client, engine = create_test_client()
    try:
        with Session(engine) as session:
            project = Project(name="Test Project")
            session.add(project)
            session.commit()
            session.refresh(project)
            project_id = project.id

        response = client.post(
            f"/api/projects/{project_id}/edits/bulk",
            json={
                "edits": [
                    {
                        "type": "cut",
                        "source": "silence_detection",
                        "start": 1.0,
                        "end": 2.5,
                        "metadata": {"duration": 1.5},
                    }
                ]
            },
        )
        assert response.status_code == 200
        edit = response.json()["edits"][0]
        assert edit["enabled"] is True
        assert edit["metadata"]["duration"] == 1.5

        response = client.patch(
            f"/api/projects/{project_id}/edits/{edit['id']}",
            json={"enabled": False},
        )
        assert response.status_code == 200
        assert response.json()["enabled"] is False

        response = client.get(f"/api/projects/{project_id}/edits")
        assert response.status_code == 200
        assert len(response.json()["edits"]) == 1

        response = client.delete(f"/api/projects/{project_id}/edits/{edit['id']}")
        assert response.status_code == 200

        response = client.get(f"/api/projects/{project_id}/edits")
        assert response.status_code == 200
        assert response.json()["edits"] == []
    finally:
        app.dependency_overrides.clear()


def test_audio_pauses_endpoint_uses_uploaded_file(tmp_path):
    client, _ = create_test_client()
    try:
        file_id = "pause-test"
        video_path = Path("temp/uploads") / f"{file_id}.mp4"
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"fake video")

        with patch("backend.app.detect_audio_pauses") as mock_detect:
            mock_detect.return_value = [
                {"start": 1.0, "end": 2.0, "duration": 1.0},
                {"start": 2.2, "end": 3.0, "duration": 0.8},
            ]
            response = client.get(
                f"/api/audio/pauses/{file_id}",
                params={"min_silence_duration": 0.5, "merge_gap": 0.5},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["pauses"][0]["start"] == 1.0
        assert body["pauses"][0]["end"] == 3.0
        assert body["total_silence_duration"] == 2.0
    finally:
        video_path.unlink(missing_ok=True)
        app.dependency_overrides.clear()


def test_render_project_applies_enabled_cut_edits():
    client, engine = create_test_client()
    try:
        file_id = "render-test"
        video_path = Path("temp/uploads") / f"{file_id}.mp4"
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"fake video")

        with Session(engine) as session:
            project = Project(name="Render Project")
            session.add(project)
            session.commit()
            session.refresh(project)
            project_id = project.id

            media_asset = MediaAsset(
                project_id=project_id,
                file_id=file_id,
                filename="source.mp4",
                file_url=f"/api/video/{file_id}",
                size=10,
            )
            session.add(media_asset)
            session.commit()

        client.post(
            f"/api/projects/{project_id}/edits/bulk",
            json={
                "edits": [
                    {
                        "type": "cut",
                        "source": "silence_detection",
                        "start": 1,
                        "end": 2,
                    },
                    {
                        "type": "cut",
                        "source": "silence_detection",
                        "start": 3,
                        "end": 4,
                    },
                ]
            },
        )

        edits = client.get(f"/api/projects/{project_id}/edits").json()["edits"]
        client.patch(
            f"/api/projects/{project_id}/edits/{edits[1]['id']}",
            json={"enabled": False},
        )

        with patch("backend.app.render_with_edits") as mock_render:
            response = client.post(f"/api/projects/{project_id}/render")

        assert response.status_code == 200
        assert response.json()["applied_edits"] == 1
        mock_render.assert_called_once()
        # args: (video_path, cut_ranges, zoom_ranges, output_path)
        assert mock_render.call_args.args[1] == [{"start": 1.0, "end": 2.0}]
        assert mock_render.call_args.args[2] == []
    finally:
        video_path.unlink(missing_ok=True)
        app.dependency_overrides.clear()


def test_render_project_applies_zoom_edits():
    client, engine = create_test_client()
    try:
        file_id = "render-zoom-test"
        video_path = Path("temp/uploads") / f"{file_id}.mp4"
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"fake video")

        with Session(engine) as session:
            project = Project(name="Zoom Project")
            session.add(project)
            session.commit()
            session.refresh(project)
            project_id = project.id

            session.add(
                MediaAsset(
                    project_id=project_id,
                    file_id=file_id,
                    filename="source.mp4",
                    file_url=f"/api/video/{file_id}",
                    size=10,
                )
            )
            session.commit()

        response = client.post(
            f"/api/projects/{project_id}/edits/bulk",
            json={
                "edits": [
                    {
                        "type": "zoom",
                        "source": "editing_plan",
                        "start": 4,
                        "end": 7,
                        "metadata": {"zoom_level": 1.5},
                    }
                ]
            },
        )
        assert response.status_code == 200

        with patch("backend.app.render_with_edits") as mock_render:
            response = client.post(f"/api/projects/{project_id}/render")

        assert response.status_code == 200
        assert response.json()["applied_edits"] == 1
        mock_render.assert_called_once()
        # No cuts, one zoom range carrying its level from the edit metadata.
        assert mock_render.call_args.args[1] == []
        assert mock_render.call_args.args[2] == [
            {"start": 4.0, "end": 7.0, "level": 1.5}
        ]
    finally:
        video_path.unlink(missing_ok=True)
        app.dependency_overrides.clear()


def test_bulk_edits_reject_unknown_type():
    client, engine = create_test_client()
    try:
        with Session(engine) as session:
            project = Project(name="Reject Project")
            session.add(project)
            session.commit()
            session.refresh(project)
            project_id = project.id

        response = client.post(
            f"/api/projects/{project_id}/edits/bulk",
            json={
                "edits": [
                    {"type": "rotate", "source": "test", "start": 1, "end": 2}
                ]
            },
        )
        assert response.status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_timeline_save_get_replace_and_clear():
    client, engine = create_test_client()
    try:
        with Session(engine) as session:
            project = Project(name="Timeline Project")
            session.add(project)
            session.commit()
            session.refresh(project)
            project_id = project.id

        # Save two segments in reversed source order; order must be preserved.
        response = client.put(
            f"/api/projects/{project_id}/timeline",
            json={
                "segments": [{"start": 5.0, "end": 10.0}, {"start": 0.0, "end": 5.0}]
            },
        )
        assert response.status_code == 200
        segments = response.json()["segments"]
        assert [(s["start"], s["end"], s["position"]) for s in segments] == [
            (5.0, 10.0, 0),
            (0.0, 5.0, 1),
        ]

        response = client.get(f"/api/projects/{project_id}/timeline")
        assert response.status_code == 200
        segments = response.json()["segments"]
        assert [s["start"] for s in segments] == [5.0, 0.0]

        # Replacing the timeline drops the previous rows.
        response = client.put(
            f"/api/projects/{project_id}/timeline",
            json={"segments": [{"start": 2.0, "end": 8.0}]},
        )
        assert response.status_code == 200
        assert len(response.json()["segments"]) == 1

        # An empty list clears the timeline entirely.
        response = client.put(
            f"/api/projects/{project_id}/timeline", json={"segments": []}
        )
        assert response.status_code == 200
        response = client.get(f"/api/projects/{project_id}/timeline")
        assert response.json()["segments"] == []

        # Invalid ranges are rejected.
        response = client.put(
            f"/api/projects/{project_id}/timeline",
            json={"segments": [{"start": 3.0, "end": 2.0}]},
        )
        assert response.status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_render_uses_timeline_when_saved():
    client, engine = create_test_client()
    file_id = "timeline-render-test"
    video_path = Path("temp/uploads") / f"{file_id}.mp4"
    try:
        with Session(engine) as session:
            project = Project(name="Timeline Render Project")
            session.add(project)
            session.commit()
            session.refresh(project)
            project_id = project.id
            session.add(
                MediaAsset(
                    project_id=project_id,
                    file_id=file_id,
                    filename="source.mp4",
                    file_url=f"/api/video/{file_id}",
                    size=10,
                )
            )
            session.commit()

        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"fake video")

        response = client.put(
            f"/api/projects/{project_id}/timeline",
            json={"segments": [{"start": 4.0, "end": 8.0}, {"start": 0.0, "end": 4.0}]},
        )
        assert response.status_code == 200

        response = client.post(
            f"/api/projects/{project_id}/edits/bulk",
            json={
                "edits": [
                    {"type": "cut", "source": "silence_detection", "start": 1, "end": 2}
                ]
            },
        )
        assert response.status_code == 200

        with patch("backend.app.render_timeline") as mock_render:
            response = client.post(f"/api/projects/{project_id}/render")

        assert response.status_code == 200
        # 2 timeline segments + 1 cut.
        assert response.json()["applied_edits"] == 3
        mock_render.assert_called_once()
        args = mock_render.call_args.args
        # Ordered segments, then the cut ranges composed within them.
        assert args[1] == [
            {"start": 4.0, "end": 8.0},
            {"start": 0.0, "end": 4.0},
        ]
        assert args[3] == [{"start": 1.0, "end": 2.0}]
    finally:
        video_path.unlink(missing_ok=True)
        app.dependency_overrides.clear()
