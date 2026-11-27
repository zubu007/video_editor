"""MCP server exposing the video editor's project workflow to AI agents.

Thin wrapper over the running FastAPI backend (default http://localhost:8000).
Run over stdio: ``uv run python mcp_server.py``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests
from mcp.server.fastmcp import FastMCP

API_BASE_URL = os.environ.get("VIDEO_EDITOR_API_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT_S = 600
UPLOAD_TIMEOUT_S = 3600
DEFAULT_TRANSCRIPT_WORDS_PER_LINE = 12
MAX_TRANSCRIPT_LINES = 200

INSTRUCTIONS = """\
Video editor workflow (all times are in SECONDS on the ORIGINAL video):
1. upload_video(path) -> project_id, file_id. Reuse these ids in later calls;
   use list_projects to find existing ones.
2. start_transcription(file_id) -> job_id; poll get_transcript(job_id) until done.
   Read only the range you need via start/end.
3. add_cut(project_id, start, end) removes that portion from the final video.
   Edits are non-destructive; list_edits / remove_edit manage them.
   Dota 2 deaths: upload with project_type="gaming", ASK THE USER for hero_slot
   (top hero bar, left to right: 0-4 Radiant, 5-9 Dire; never guess), then
   detect_deaths(file_id, hero_slot) -> poll get_death_intervals(job_id) ->
   cut_deaths(project_id, job_id) to save all deaths as cuts.
4. render_project(project_id) -> job_id; poll get_render_status(job_id) until done.
The backend must be running (python run_server.py). Pass local file paths, never bytes.
"""

mcp = FastMCP("video-editor", instructions=INSTRUCTIONS)

# job_id -> word list, so paging through a transcript doesn't re-fetch it.
_transcript_cache: dict[str, list[dict[str, Any]]] = {}


class ApiError(RuntimeError):
    """Raised when the backend returns an error, with an actionable message."""


def _call(method: str, path: str, **kwargs: Any) -> Any:
    """Call the backend and return parsed JSON, raising ApiError on failure."""
    kwargs.setdefault("timeout", REQUEST_TIMEOUT_S)
    try:
        response = requests.request(method, f"{API_BASE_URL}{path}", **kwargs)
    except requests.ConnectionError as exc:
        raise ApiError(
            f"Cannot reach backend at {API_BASE_URL}. Start it with `python run_server.py`."
        ) from exc
    if not response.ok:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise ApiError(f"{method} {path} failed ({response.status_code}): {detail}")
    return response.json()


def _format_time(seconds: float) -> str:
    return f"{seconds:.2f}"


@mcp.tool()
def list_projects() -> list[dict[str, Any]]:
    """List saved projects (newest first) with their ids and source availability."""
    data = _call("GET", "/api/projects")
    return [
        {
            "project_id": p["id"],
            "name": p["name"],
            "project_type": p["project_type"],
            "file_id": p.get("file_id"),
            "duration": p.get("duration"),
            "source_available": p["source_available"],
            "edit_count": p["edit_count"],
        }
        for p in data["projects"]
    ]


@mcp.tool()
def upload_video(
    path: str, project_name: str | None = None, project_type: str = "standard"
) -> dict[str, Any]:
    """Upload a local video file and create a project for it.

    Args:
        path: Absolute path to a video file on this machine.
        project_name: Optional project name (defaults to the file name).
        project_type: "standard" or "gaming".

    Returns:
        project_id and file_id (use them in all later calls) plus duration in seconds.
    """
    video = Path(path).expanduser()
    if not video.is_file():
        raise ApiError(f"File not found: {video}")
    data: dict[str, str] = {"project_type": project_type}
    if project_name:
        data["project_name"] = project_name
    with video.open("rb") as handle:
        result = _call(
            "POST",
            "/api/video/upload",
            files={"video": (video.name, handle)},
            data=data,
            timeout=UPLOAD_TIMEOUT_S,
        )
    return {
        "project_id": result["project_id"],
        "file_id": result["file_id"],
        "filename": result["filename"],
        "duration": result.get("duration"),
    }


@mcp.tool()
def start_transcription(file_id: str, model_size: str = "base") -> dict[str, str]:
    """Start a background word-level transcription of an uploaded video.

    Args:
        file_id: file_id returned by upload_video.
        model_size: Whisper size (tiny, base, small, medium, large); bigger is slower.

    Returns:
        job_id to pass to get_transcript.
    """
    result = _call(
        "POST", f"/api/transcript/words/{file_id}/start", params={"model_size": model_size}
    )
    return {"job_id": result["job_id"], "status": result["status"]}


@mcp.tool()
def get_transcript(
    job_id: str, start: float = 0.0, end: float | None = None
) -> str:
    """Get transcription status, or the transcript text once finished.

    Output is compact lines of ``[start-end] text`` (seconds). Narrow ``start``/``end``
    to read only the part you need; output is capped at 200 lines, and the last line
    says where to continue.

    Args:
        job_id: job_id from start_transcription.
        start: Only include words starting at or after this time (seconds).
        end: Only include words starting before this time (seconds); None = to the end.
    """
    words = _transcript_cache.get(job_id)
    if words is None:
        status = _call("GET", f"/api/transcript/words/status/{job_id}")
        if status["status"] == "error":
            raise ApiError(f"Transcription failed: {status.get('error')}")
        if status["status"] != "done":
            return f"status={status['status']} progress={status['progress']:.0%}; poll again"
        words = status["words"]
        _transcript_cache[job_id] = words

    selected = [
        w for w in words if w["start"] >= start and (end is None or w["start"] < end)
    ]
    if not selected:
        return f"No words in range (transcript has {len(words)} words)."

    lines: list[str] = []
    chunk_size = DEFAULT_TRANSCRIPT_WORDS_PER_LINE
    for i in range(0, len(selected), chunk_size):
        chunk = selected[i : i + chunk_size]
        text = " ".join(w["word"].strip() for w in chunk)
        lines.append(f"[{_format_time(chunk[0]['start'])}-{_format_time(chunk[-1]['end'])}] {text}")
        if len(lines) == MAX_TRANSCRIPT_LINES and i + chunk_size < len(selected):
            lines.append(
                f"... truncated; continue with start={_format_time(selected[i + chunk_size]['start'])}"
            )
            break
    return "\n".join(lines)


@mcp.tool()
def add_cut(project_id: str, start: float, end: float) -> dict[str, Any]:
    """Cut out a portion of the video: [start, end] is removed from the final render.

    Times are seconds on the original video. Non-destructive; the cut is stored as an
    edit and only applied by render_project. Undo with remove_edit.

    Returns:
        edit_id of the created cut.
    """
    if start < 0 or end <= start:
        raise ApiError("Require 0 <= start < end (seconds).")
    result = _call(
        "POST",
        f"/api/projects/{project_id}/edits/bulk",
        json={"edits": [{"type": "cut", "source": "mcp", "start": start, "end": end}]},
    )
    edit = result["edits"][0]
    return {"edit_id": edit["id"], "start": edit["start"], "end": edit["end"]}


@mcp.tool()
def list_edits(project_id: str) -> list[dict[str, Any]]:
    """List the project's stored edits (id, type, start, end, enabled)."""
    result = _call("GET", f"/api/projects/{project_id}/edits")
    return [
        {
            "edit_id": e["id"],
            "type": e["type"],
            "start": e["start"],
            "end": e["end"],
            "enabled": e["enabled"],
        }
        for e in result["edits"]
    ]


@mcp.tool()
def remove_edit(project_id: str, edit_id: str) -> str:
    """Delete a stored edit (e.g. undo a cut) by its edit_id."""
    _call("DELETE", f"/api/projects/{project_id}/edits/{edit_id}")
    return f"Removed edit {edit_id}."


def _slot_to_team(hero_slot: int) -> tuple[str, int]:
    """Map a 0-9 hero number to (team, 0-based slot within that team's bar)."""
    if not 0 <= hero_slot <= 9:
        raise ApiError(
            "hero_slot must be 0-9: 0-4 = Radiant left to right, "
            "5-9 = Dire left to right in the top hero bar."
        )
    return ("radiant", hero_slot) if hero_slot < 5 else ("dire", hero_slot - 5)


@mcp.tool()
def detect_deaths(file_id: str, hero_slot: int) -> dict[str, str]:
    """Start Dota 2 death detection for the player's hero (gaming recordings).

    Reads the top hero bar's respawn-countdown box for the given portrait, so it
    does not depend on which hero the bottom HUD currently shows. ASK THE USER for
    hero_slot; never guess it.

    Args:
        file_id: file_id returned by upload_video.
        hero_slot: Portrait position in the top bar, counted left to right:
            0-4 = Radiant heroes, 5-9 = Dire heroes.

    Returns:
        job_id to pass to get_death_intervals.
    """
    team, slot = _slot_to_team(hero_slot)
    result = _call(
        "POST",
        f"/api/gaming/detect-deaths/{file_id}",
        params={"team": team, "player_slot": slot},
    )
    return {"job_id": result["job_id"], "status": result["status"]}


@mcp.tool()
def get_death_intervals(job_id: str) -> str:
    """Get death-detection status, or the detected dead intervals once finished.

    Output lines are ``start-end (duration s)`` in seconds on the original video.
    """
    result = _call("GET", f"/api/gaming/death-detect/status/{job_id}")
    if result["status"] == "error":
        raise ApiError(f"Death detection failed: {result.get('error')}")
    if result["status"] != "done":
        return f"status={result['status']}; poll again"
    intervals = result["intervals"]
    if not intervals:
        return "Done: no deaths detected. Check that hero_slot is correct."
    lines = [
        f"{_format_time(iv['start'])}-{_format_time(iv['end'])} ({iv['duration']:.1f}s)"
        for iv in intervals
    ]
    total = sum(iv["duration"] for iv in intervals)
    return f"{len(intervals)} deaths, {total:.0f}s total\n" + "\n".join(lines)


@mcp.tool()
def cut_deaths(
    project_id: str, job_id: str, padding_seconds: float = 0.0
) -> dict[str, Any]:
    """Save every detected death interval as a cut (applied by render_project).

    Skips intervals already stored as identical cuts, so it is safe to call twice.

    Args:
        project_id: Project the detection was run for.
        job_id: job_id from detect_deaths (must be finished).
        padding_seconds: Extra time removed before each death and after each respawn.
    """
    if padding_seconds < 0:
        raise ApiError("padding_seconds must be >= 0.")
    status = _call("GET", f"/api/gaming/death-detect/status/{job_id}")
    if status["status"] != "done":
        raise ApiError(f"Detection not finished (status={status['status']}).")

    existing = {
        (round(e["start"], 3), round(e["end"], 3))
        for e in _call("GET", f"/api/projects/{project_id}/edits")["edits"]
        if e["type"] == "cut"
    }
    new_edits = []
    for iv in status["intervals"]:
        start = max(0.0, iv["start"] - padding_seconds)
        end = iv["end"] + padding_seconds
        if (round(start, 3), round(end, 3)) not in existing:
            new_edits.append(
                {"type": "cut", "source": "death_detection", "start": start, "end": end}
            )
    if new_edits:
        _call(
            "POST",
            f"/api/projects/{project_id}/edits/bulk",
            json={"edits": new_edits},
        )
    return {
        "cuts_added": len(new_edits),
        "already_present": len(status["intervals"]) - len(new_edits),
    }


@mcp.tool()
def render_project(project_id: str) -> dict[str, str]:
    """Start rendering the project with all enabled edits applied.

    Returns:
        job_id to poll with get_render_status.
    """
    result = _call("POST", f"/api/projects/{project_id}/render")
    return {"job_id": result["job_id"], "status": result["status"]}


@mcp.tool()
def get_render_status(job_id: str) -> dict[str, Any]:
    """Get render progress (0-1) and, once status is "done", the output location."""
    result = _call("GET", f"/api/render/status/{job_id}")
    summary: dict[str, Any] = {
        "status": result["status"],
        "progress": round(result["progress"], 2),
    }
    if result.get("error"):
        summary["error"] = result["error"]
    if result["status"] == "done":
        summary["output_url"] = f"{API_BASE_URL}{result['output_url']}"
        summary["filename"] = result.get("filename")
        summary["applied_edits"] = result.get("applied_edits")
    return summary


if __name__ == "__main__":
    mcp.run()
