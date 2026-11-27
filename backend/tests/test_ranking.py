"""Tests for the Ranking Shorts feature."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from backend.app import app
from backend.features.project_io import (
    ProjectFile,
    build_project_file,
    load_project_file,
)
from backend.features.ranking import compose, jobs, store
from backend.features.ranking.download import validate_source_url
from backend.features.ranking.schema import (
    RankingDocument,
    default_document,
    merge_client_document,
)
from backend.features.ranking.timeline import (
    build_schedule,
    frames_for,
    revealed_clip_ids,
    segment_index_at,
)
from backend.storage.database import get_session


@pytest.fixture()
def env():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)

    def override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override
    created: list[Path] = []
    yield TestClient(app), engine, created
    app.dependency_overrides.pop(get_session, None)
    for path in created:
        path.unlink(missing_ok=True)
    for pattern in ("ranking_*",):
        for path in store.OUTPUT_DIR.glob(pattern):
            path.unlink(missing_ok=True)


def make_video(
    path: Path, color: str, seconds: float = 1.0, size: str = "320x240", audio=True
) -> Path:
    command = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s={size}:r=24:d={seconds}",
    ]
    if audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    command += ["-pix_fmt", "yuv420p", "-shortest", str(path)]
    subprocess.run(command, check=True)
    return path


def create_project(client: TestClient) -> dict:
    response = client.post("/api/ranking/projects", json={})
    assert response.status_code == 200
    return response.json()


def save(client: TestClient, payload: dict, document: dict) -> dict:
    response = client.put(
        f"/api/ranking/projects/{payload['project']['id']}",
        json={"revision": payload["revision"], "document": document},
    )
    assert response.status_code == 200, response.text
    return response.json()


def upload(client: TestClient, payload: dict, clip_id: str, path: Path) -> dict:
    with path.open("rb") as handle:
        response = client.post(
            f"/api/ranking/projects/{payload['project']['id']}/clips/{clip_id}/upload",
            files={"video": (path.name, handle, "video/mp4")},
        )
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------- pure logic


def test_frame_quantisation_and_schedule():
    assert frames_for(0, 1.0) == 30
    assert frames_for(0, 0.0167) == 1  # never below one frame
    assert frames_for(0, 0.05) == 2  # 1.5 rounds half-up

    doc = default_document("p")
    for clip in doc.clips:
        clip.trim_out = 2.0
        clip.playback_order = 6 - clip.rank
    schedule = build_schedule(doc)
    assert [s.start_frame for s in schedule.segments] == [0, 60, 120, 180, 240]
    assert schedule.total_frames == 300
    assert schedule.segments[0].clip_id == doc.clips[4].id


def test_reveal_is_pure_function_of_time():
    doc = default_document("p")
    for clip in doc.clips:
        clip.trim_out = 1.0
    # countdown 5,4,3,2,1
    for clip in doc.clips:
        clip.playback_order = 6 - clip.rank
    schedule = build_schedule(doc)
    by_rank = {c.rank: c.id for c in doc.clips}
    assert revealed_clip_ids(schedule, 0) == [by_rank[5]]
    assert revealed_clip_ids(schedule, 29) == [by_rank[5]]
    assert revealed_clip_ids(schedule, 30) == [by_rank[5], by_rank[4]]  # half-open
    assert len(revealed_clip_ids(schedule, 149)) == 5
    assert revealed_clip_ids(schedule, 10_000) == revealed_clip_ids(schedule, 149)
    assert segment_index_at(schedule, 59) == 1
    assert revealed_clip_ids(schedule, 5) == [by_rank[5]]  # seek back hides names


def test_schema_invariants():
    doc = default_document("p")
    payload = doc.model_dump()
    payload["clips"][0]["rank"] = 2
    with pytest.raises(ValueError):
        RankingDocument.model_validate(payload)
    payload = doc.model_dump()
    payload["clips"] = payload["clips"][:1]
    with pytest.raises(ValueError):
        RankingDocument.model_validate(payload)


def test_server_owned_fields_cannot_be_forged():
    stored = default_document("p")
    stored.clips[0].asset_id = "real"
    incoming = stored.model_dump()
    incoming["clips"][0]["asset_id"] = "forged"
    incoming["clips"][0]["source_generation"] = 99
    merged = merge_client_document(stored, incoming)
    assert merged.clips[0].asset_id == "real"
    assert merged.clips[0].source_generation == 0


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/x",
        "https://127.0.0.1/video",
        "file:///etc/passwd",
        "https://evil.com/watch?v=1",
        "https://youtube.com.evil.com/watch?v=1",
        "https://www.youtube.com/playlist?list=1",
        "https://www.instagram.com/someuser/",
        "https://user:pw@www.youtube.com/watch?v=1",
    ],
)
def test_url_validation_rejects(url):
    with pytest.raises(ValueError):
        validate_source_url(url)


def test_url_validation_accepts_providers():
    assert validate_source_url("https://www.youtube.com/shorts/abc") == "youtube"
    assert validate_source_url("https://youtu.be/abc") == "youtube"
    assert validate_source_url("https://www.instagram.com/reel/abc/") == "instagram"


def test_overlay_reveals_names_and_detects_overflow():
    doc = default_document("p")
    for i, clip in enumerate(doc.clips):
        clip.name = f"Name {i}"
        clip.trim_out = 1.0
    first = compose.render_overlay(doc, [doc.clips[0].id], doc.clips[0].id)
    last = compose.render_overlay(doc, [c.id for c in doc.clips], doc.clips[4].id)
    assert first.size == (1080, 1920)
    # title column of rank 5 is empty in the first state, drawn in the last
    box = (170, 1264, 700, 1500)
    assert first.crop(box).getbbox() is None
    assert last.crop(box).getbbox() is not None
    assert compose.layout_issues(doc) == []

    doc.clips[1].name = "W" * 119
    assert any(i.field == f"clip:{doc.clips[1].id}" for i in compose.layout_issues(doc))
    doc.clips[1].name = "ok \U0001f600"
    assert any("cannot draw" in i.message for i in compose.layout_issues(doc))


# ----------------------------------------------------------------------- API


def test_create_save_conflict_and_ownership(env):
    client, _, _ = env
    payload = create_project(client)
    assert len(payload["document"]["clips"]) == 5
    assert payload["issues"]  # names/media missing -> export blocked

    document = payload["document"]
    document["heading"]["runs"] = [
        {"text": "Top 5 ", "color": "#ffd400"},
        {"text": "failed tattoos", "color": None},
    ]
    document["clips"][0]["name"] = "First"
    saved = save(client, payload, document)
    assert saved["revision"] == payload["revision"] + 1

    stale = client.put(
        f"/api/ranking/projects/{payload['project']['id']}",
        json={"revision": payload["revision"], "document": document},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["current_revision"] == saved["revision"]

    document["clips"][0]["rank"] = 1
    document["clips"][1]["rank"] = 1
    bad = client.put(
        f"/api/ranking/projects/{payload['project']['id']}",
        json={"revision": saved["revision"], "document": document},
    )
    assert bad.status_code == 422

    listing = client.get("/api/projects").json()["projects"]
    entry = next(p for p in listing if p["id"] == payload["project"]["id"])
    assert entry["project_type"] == "ranking"
    assert entry["source_available"] and entry["missing_sources"] == 5

    reopened = client.get(f"/api/ranking/projects/{payload['project']['id']}").json()
    assert reopened["document"]["clips"][0]["name"] == "First"


def test_download_rejects_bad_url_and_overlay_endpoint(env):
    client, _, _ = env
    payload = create_project(client)
    clip_id = payload["document"]["clips"][0]["id"]
    response = client.post(
        f"/api/ranking/projects/{payload['project']['id']}/clips/{clip_id}/download",
        json={"url": "http://localhost:8000/secret"},
    )
    assert response.status_code == 400
    overlay = client.post(
        "/api/ranking/overlay",
        json={"document": payload["document"], "active_index": 2},
    )
    assert overlay.status_code == 200
    assert overlay.headers["content-type"] == "image/png"


def test_stale_generation_cannot_attach(env, tmp_path):
    client, engine, created = env
    payload = create_project(client)
    project_id = payload["project"]["id"]
    clip_id = payload["document"]["clips"][0]["id"]

    file_id = "stale-test-file"
    path = make_video(store.UPLOAD_DIR / f"{file_id}.mp4", "red")
    created.append(path)
    # generation 7 never matches the stored generation 0
    assert not store.attach_source(
        engine, project_id, clip_id, 7, file_id, "x.mp4", "t"
    )
    assert not path.exists()  # stale file removed

    file_id = "removed-clip-file"
    path = make_video(store.UPLOAD_DIR / f"{file_id}.mp4", "red")
    created.append(path)
    assert not store.attach_source(
        engine, project_id, "no-such-clip", 0, file_id, "x", None
    )

    file_id = "deleted-project-file"
    path = make_video(store.UPLOAD_DIR / f"{file_id}.mp4", "red")
    created.append(path)
    client.delete(f"/api/projects/{project_id}")
    assert not store.attach_source(engine, project_id, clip_id, 0, file_id, "x", None)


def test_upload_rejects_non_video(env, tmp_path):
    client, _, _ = env
    payload = create_project(client)
    clip_id = payload["document"]["clips"][0]["id"]
    bogus = tmp_path / "bogus.mp4"
    bogus.write_bytes(b"not a video")
    with bogus.open("rb") as handle:
        response = client.post(
            f"/api/ranking/projects/{payload['project']['id']}/clips/{clip_id}/upload",
            files={"video": ("bogus.mp4", handle, "video/mp4")},
        )
    assert response.status_code == 400
    assert not list(store.UPLOAD_DIR.glob("*bogus*"))


def build_ready_project(client, tmp_path, created):
    """Five uploaded sources: landscape, portrait, silent, rotated-size mix."""
    payload = create_project(client)
    specs = [
        ("red", "320x240", True),
        ("green", "240x320", True),
        ("blue", "320x240", False),
        ("yellow", "400x400", True),
        ("purple", "320x240", True),
    ]
    clips = payload["document"]["clips"]
    for clip, (color, size, audio) in zip(clips, specs, strict=True):
        path = make_video(tmp_path / f"{color}.mp4", color, 1.0, size, audio)
        payload = upload(client, payload, clip["id"], path)
    document = payload["document"]
    for i, clip in enumerate(document["clips"]):
        clip["name"] = f"Entry {i + 1}"
        created.append(store.find_media_path(payload["media"][clip["id"]]["file_id"]))
    return save(client, payload, document)


def wait_for(client, job_id, timeout=240):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/api/ranking/jobs/{job_id}").json()
        if status["status"] in ("done", "error", "cancelled"):
            return status
        time.sleep(0.5)
    raise AssertionError("job timed out")


def test_render_and_vedit_round_trip(env, tmp_path):
    client, engine, created = env
    payload = build_ready_project(client, tmp_path, created)
    project_id = payload["project"]["id"]
    assert payload["issues"] == []
    assert payload["timeline"]["total_frames"] == 150

    # countdown order + trim the first entry
    document = payload["document"]
    for clip in document["clips"]:
        clip["playback_order"] = 6 - clip["rank"]
    document["clips"][0]["muted"] = True
    payload = save(client, payload, document)

    started = client.post(
        f"/api/ranking/projects/{project_id}/render",
        json={"revision": payload["revision"]},
    )
    assert started.status_code == 200, started.text
    status = wait_for(client, started.json()["job_id"])
    assert status["status"] == "done", status
    output = store.OUTPUT_DIR / status["result"]["filename"]
    assert output.exists() and not Path(str(output) + ".partial").exists()

    probe = json.loads(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-count_frames",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=nb_read_frames,width,height",
                "-of",
                "json",
                str(output),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )["streams"][0]
    assert (probe["width"], probe["height"]) == (1080, 1920)
    assert int(probe["nb_read_frames"]) == 150

    # The first segment is rank 5 (purple); the second is rank 4 (yellow).
    def pixel(frame: int) -> tuple[int, int, int]:
        raw = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(output),
                "-vf",
                f"select=eq(n\\,{frame}),crop=4:4:900:960",
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-",
            ],
            capture_output=True,
        )
        assert raw.returncode == 0, raw.stderr.decode()
        return tuple(raw.stdout[:3])

    last_of_first, first_of_second = pixel(29), pixel(30)
    assert last_of_first != first_of_second
    assert last_of_first[0] > 100 and last_of_first[1] < 80  # purple-ish (r>g)
    assert first_of_second[0] > 150 and first_of_second[1] > 150  # yellow

    # .vedit round trip restores composition and assets
    with Session(engine) as session:
        document_file = build_project_file(session, project_id, store_resolver)
    assert document_file.version == 2 and document_file.ranking is not None
    restored = ProjectFile.model_validate_json(document_file.model_dump_json())
    with Session(engine) as session:
        result = load_project_file(
            session, restored, upload_dir=store.UPLOAD_DIR, output_dir=store.OUTPUT_DIR
        )
        new_id = result.project_id
    assert new_id != project_id
    reopened = client.get(f"/api/ranking/projects/{new_id}").json()
    assert reopened["document"]["project_id"] == new_id
    assert [c["playback_order"] for c in reopened["document"]["clips"]] == [
        c["playback_order"] for c in payload["document"]["clips"]
    ]
    assert all(m["available"] for m in reopened["media"].values())
    old_assets = {c["asset_id"] for c in payload["document"]["clips"]}
    assert not old_assets & {c["asset_id"] for c in reopened["document"]["clips"]}

    # deleting a project removes composition + renders but not the other project's data
    assert client.delete(f"/api/projects/{project_id}").status_code == 200
    assert not output.exists()
    assert client.get(f"/api/ranking/projects/{project_id}").status_code == 404
    assert client.get(f"/api/ranking/projects/{new_id}").status_code == 200


def store_resolver(file_id: str):
    return store.find_media_path(file_id)


def test_one_active_render_per_project(env, tmp_path):
    client, _, created = env
    payload = build_ready_project(client, tmp_path, created)
    blocker = jobs.create_job("render", payload["project"]["id"])
    response = client.post(f"/api/ranking/projects/{payload['project']['id']}/render")
    assert response.status_code == 409
    jobs.cancel_job(blocker.job_id)


def test_cancel_marks_job(env):
    client, _, _ = env
    payload = create_project(client)
    job = jobs.create_job("render", payload["project"]["id"])
    response = client.post(f"/api/ranking/jobs/{job.job_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    jobs.update_job(job.job_id, status="done")
    assert jobs.get_job(job.job_id).status == "cancelled"
