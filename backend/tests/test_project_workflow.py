from pathlib import Path
from unittest.mock import patch

import pytest

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from backend.app import app
from backend.features.video_cutter import jobs as render_jobs
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


def render_and_wait(client, project_id):
    """Start a render job and return its final status payload.

    Rendering now runs as a background job (``POST`` returns a ``job_id``). Under
    ``TestClient`` the ``BackgroundTasks`` run to completion before ``post``
    returns, so the job is already terminal when we poll its status. Must be called
    inside any ``patch`` that should cover the actual render worker.
    """
    start = client.post(f"/api/projects/{project_id}/render")
    assert start.status_code == 200
    job_id = start.json()["job_id"]
    status = client.get(f"/api/render/status/{job_id}")
    assert status.status_code == 200
    return status.json()


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
                params={
                    "min_silence_duration": 0.5,
                    "merge_gap": 0.5,
                    "padding": 0.0,
                },
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


def test_audio_pauses_endpoint_applies_padding():
    """Padding shrinks each cut so it doesn't land flush against speech."""
    client, _ = create_test_client()
    try:
        file_id = "pause-padding-test"
        video_path = Path("temp/uploads") / f"{file_id}.mp4"
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"fake video")

        with patch("backend.app.detect_audio_pauses") as mock_detect:
            mock_detect.return_value = [
                {"start": 1.0, "end": 3.0, "duration": 2.0},
                # Too short to survive a cushion on both sides.
                {"start": 10.0, "end": 10.15, "duration": 0.15},
            ]
            response = client.get(
                f"/api/audio/pauses/{file_id}",
                params={"merge_gap": 0.5, "padding": 0.25},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["pauses"][0]["start"] == pytest.approx(1.25)
        assert body["pauses"][0]["end"] == pytest.approx(2.75)
        assert body["pauses"][0]["duration"] == pytest.approx(1.5)
        assert body["settings"]["padding"] == 0.25
    finally:
        video_path.unlink(missing_ok=True)
        app.dependency_overrides.clear()


def test_audio_pauses_endpoint_rejects_negative_padding():
    client, _ = create_test_client()
    try:
        file_id = "pause-negative-padding"
        video_path = Path("temp/uploads") / f"{file_id}.mp4"
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"fake video")

        response = client.get(f"/api/audio/pauses/{file_id}", params={"padding": -0.5})

        assert response.status_code == 400
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
            result = render_and_wait(client, project_id)

        assert result["status"] == "done"
        assert result["applied_edits"] == 1
        mock_render.assert_called_once()
        # args: (video_path, cut_ranges, zoom_ranges, output_path)
        assert mock_render.call_args.args[1] == [{"start": 1.0, "end": 2.0}]
        assert mock_render.call_args.args[2] == []
    finally:
        video_path.unlink(missing_ok=True)
        app.dependency_overrides.clear()


def test_render_job_records_progress_and_failure():
    """A failing encode is reported on the job, not raised at the start request."""
    client, engine = create_test_client()
    try:
        file_id = "render-failure-test"
        video_path = Path("temp/uploads") / f"{file_id}.mp4"
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"fake video")

        with Session(engine) as session:
            project = Project(name="Failing Project")
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

        with patch("backend.app.render_with_edits", side_effect=RuntimeError("boom")):
            result = render_and_wait(client, project_id)

        assert result["status"] == "error"
        assert "boom" in result["error"]
        assert result["output_url"] is None
    finally:
        video_path.unlink(missing_ok=True)
        app.dependency_overrides.clear()


def test_render_status_unknown_job_returns_404():
    client, _ = create_test_client()
    try:
        response = client.get("/api/render/status/does-not-exist")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_render_forwards_encoder_progress_to_job():
    """Progress reported by the encoder is visible on the job while it runs."""
    client, engine = create_test_client()
    try:
        file_id = "render-progress-test"
        video_path = Path("temp/uploads") / f"{file_id}.mp4"
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"fake video")

        with Session(engine) as session:
            project = Project(name="Progress Project")
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

        # Capture the job the endpoint creates so the fake encoder can read its
        # progress back out of the registry mid-render.
        created = {}

        def spy_create(pid):
            job = render_jobs.create_job(pid)
            created["job_id"] = job.job_id
            return job

        # Stand in for the encoder: report a mid-render fraction, then record what
        # the job registry exposes at that moment.
        observed = {}

        def fake_render(*args, **kwargs):
            kwargs["on_progress"](0.5)
            observed["mid_render"] = render_jobs.get_job(created["job_id"]).progress

        with (
            patch("backend.app.create_render_job", side_effect=spy_create),
            patch("backend.app.render_with_edits", side_effect=fake_render),
        ):
            result = render_and_wait(client, project_id)

        assert observed["mid_render"] == 0.5
        assert result["status"] == "done"
        assert result["progress"] == 1.0
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
            result = render_and_wait(client, project_id)

        assert result["status"] == "done"
        assert result["applied_edits"] == 1
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
                "edits": [{"type": "rotate", "source": "test", "start": 1, "end": 2}]
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
            result = render_and_wait(client, project_id)

        assert result["status"] == "done"
        # 2 timeline segments + 1 cut.
        assert result["applied_edits"] == 3
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


def test_render_project_burns_captions_with_remapped_words():
    client, engine = create_test_client()
    video_path = Path("temp/uploads") / "render-captions-test.mp4"
    try:
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"fake video")

        with Session(engine) as session:
            project = Project(name="Captions Project")
            session.add(project)
            session.commit()
            session.refresh(project)
            project_id = project.id

            media_asset = MediaAsset(
                project_id=project_id,
                file_id="render-captions-test",
                filename="source.mp4",
                file_url="/api/video/render-captions-test",
                size=10,
            )
            session.add(media_asset)
            session.commit()

        response = client.post(
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
                        "type": "captions",
                        "source": "captions_tool",
                        "start": 0,
                        "end": 10,
                        "metadata": {
                            "style": "rainbow",
                            "words": [
                                {"start": 0.2, "end": 0.8, "word": "Hello"},
                                {"start": 1.2, "end": 1.8, "word": "silent"},
                                {"start": 2.2, "end": 2.8, "word": "world"},
                            ],
                        },
                    },
                ]
            },
        )
        assert response.status_code == 200

        with (
            patch("backend.app.render_with_edits") as mock_render,
            patch("backend.app.add_captions") as mock_burn,
            patch("backend.app.video_duration", return_value=10.0),
        ):
            result = render_and_wait(client, project_id)

        assert result["status"] == "done"
        assert result["applied_edits"] == 2

        # MoviePy renders to an intermediate file; captions burn to the final name.
        assert Path(mock_render.call_args.args[3]).name.startswith("precaption_")
        mock_burn.assert_called_once()
        # The word inside the cut is dropped; the word after it shifts left 1s.
        remapped = mock_burn.call_args.args[1]
        assert [w["word"] for w in remapped] == ["Hello", "world"]
        assert remapped[0]["start"] == pytest.approx(0.2)
        assert remapped[1]["start"] == pytest.approx(1.2)
        assert remapped[1]["end"] == pytest.approx(1.8)
        assert Path(mock_burn.call_args.args[2]).name == result["filename"]
        assert mock_burn.call_args.kwargs["style"] == "rainbow"
    finally:
        video_path.unlink(missing_ok=True)
        app.dependency_overrides.clear()


def test_render_project_transcribes_when_captions_edit_has_no_words():
    client, engine = create_test_client()
    video_path = Path("temp/uploads") / "render-captions-fallback.mp4"
    try:
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"fake video")

        with Session(engine) as session:
            project = Project(name="Captions Fallback Project")
            session.add(project)
            session.commit()
            session.refresh(project)
            project_id = project.id

            media_asset = MediaAsset(
                project_id=project_id,
                file_id="render-captions-fallback",
                filename="source.mp4",
                file_url="/api/video/render-captions-fallback",
                size=10,
            )
            session.add(media_asset)
            session.commit()

        client.post(
            f"/api/projects/{project_id}/edits/bulk",
            json={
                "edits": [
                    {
                        "type": "captions",
                        "source": "captions_tool",
                        "start": 0,
                        "end": 10,
                    }
                ]
            },
        )

        with (
            patch("backend.app.render_with_edits"),
            patch("backend.app.add_captions") as mock_burn,
            patch("backend.app.video_duration", return_value=10.0),
            patch("backend.app.extract_transcript_as_words") as mock_words,
        ):
            mock_words.return_value = [{"start": 0.2, "end": 0.8, "word": "Hi"}]
            result = render_and_wait(client, project_id)

        assert result["status"] == "done"
        mock_words.assert_called_once()
        assert mock_burn.call_args.args[1] == [{"start": 0.2, "end": 0.8, "word": "Hi"}]
        # No explicit style falls back to the default preset.
        assert mock_burn.call_args.kwargs["style"] == "bold-pop"
    finally:
        video_path.unlink(missing_ok=True)
        app.dependency_overrides.clear()


def test_bulk_edits_reject_unknown_caption_style():
    client, engine = create_test_client()
    try:
        with Session(engine) as session:
            project = Project(name="Style Validation Project")
            session.add(project)
            session.commit()
            session.refresh(project)
            project_id = project.id

        response = client.post(
            f"/api/projects/{project_id}/edits/bulk",
            json={
                "edits": [
                    {
                        "type": "captions",
                        "source": "captions_tool",
                        "start": 0,
                        "end": 10,
                        "metadata": {"style": "comic-sans"},
                    }
                ]
            },
        )
        assert response.status_code == 400
        assert "Unknown caption style" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_caption_styles_endpoint_lists_presets():
    client, _ = create_test_client()
    try:
        response = client.get("/api/captions/styles")
        assert response.status_code == 200
        body = response.json()
        names = [style["name"] for style in body["styles"]]
        assert "bold-pop" in names
        assert body["default_style"] in names
        bold_pop = next(s for s in body["styles"] if s["name"] == "bold-pop")
        assert bold_pop["highlight_colour"] == "#FFD900"
    finally:
        app.dependency_overrides.clear()
