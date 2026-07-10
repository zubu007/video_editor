"""
Tools the project assistant agent can invoke to inspect and edit a project.

Each tool is registered with a Groq/OpenAI-style function schema (sent to the
LLM) and a handler that executes against the project database. Handlers return
JSON-serializable dicts with a human-readable "summary" the UI shows as an
activity log line; user-level failures raise ToolError, which the agent loop
feeds back to the model instead of aborting the conversation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from sqlmodel import Session, select

from backend.features.audio_pause.detect import (
    detect_audio_pauses,
    get_total_silence_duration,
    merge_nearby_pauses,
)
from backend.storage.database import (
    EditOperation,
    MediaAsset,
    Project,
    touch_project,
    utc_now,
)

# Edit types the agent may create or modify. Timeline segments are managed by
# their own endpoints and are deliberately out of the agent's reach for now.
AGENT_EDIT_TYPES = {"cut", "zoom"}
PROTECTED_EDIT_TYPE = "timeline_segment"

MIN_ZOOM_LEVEL = 1.0
MAX_ZOOM_LEVEL = 3.0


class ToolError(Exception):
    """A tool failure the LLM should see and recover from (not a server bug)."""


@dataclass
class ToolContext:
    """Everything a tool handler may need to act on the current project."""

    session: Session
    project: Project
    media_asset: Optional[MediaAsset] = None
    video_path: Optional[Path] = None


@dataclass
class ToolResult:
    """Outcome of one tool execution."""

    data: dict[str, Any]
    summary: str
    mutated_edits: bool = False
    ok: bool = True


@dataclass
class ToolSpec:
    """A tool the agent can call: LLM-facing schema plus its handler."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[ToolContext, dict[str, Any]], ToolResult]
    mutates: bool = False


def _duration_limit(context: ToolContext) -> Optional[float]:
    """Source video duration when known, for range validation."""
    if context.media_asset is not None and context.media_asset.duration:
        return context.media_asset.duration
    return None


def _validate_range(context: ToolContext, start: float, end: float) -> tuple[float, float]:
    """Validate a time range against the source video; returns (start, end)."""
    try:
        start = float(start)
        end = float(end)
    except (TypeError, ValueError):
        raise ToolError("start and end must be numbers (seconds)")
    if start < 0 or start >= end:
        raise ToolError("Range must satisfy 0 <= start < end")
    duration = _duration_limit(context)
    if duration is not None and end > duration + 0.05:
        raise ToolError(
            f"Range ends at {end:.1f}s but the video is only {duration:.1f}s long"
        )
    return start, end


def _get_agent_editable_edit(context: ToolContext, edit_id: str) -> EditOperation:
    """Fetch an edit by id, rejecting unknown ids and timeline segments."""
    edit = context.session.get(EditOperation, str(edit_id))
    if edit is None or edit.project_id != context.project.id:
        raise ToolError(f"No edit with id '{edit_id}' in this project")
    if edit.type == PROTECTED_EDIT_TYPE:
        raise ToolError("Timeline segments cannot be modified through chat yet")
    return edit


def _edit_to_dict(edit: EditOperation) -> dict[str, Any]:
    return {
        "id": edit.id,
        "type": edit.type,
        "start": edit.start,
        "end": edit.end,
        "enabled": edit.enabled,
        "source": edit.source,
        "details": edit.details or {},
    }


def _create_edit(
    context: ToolContext,
    edit_type: str,
    start: float,
    end: float,
    details: dict[str, Any],
) -> EditOperation:
    edit = EditOperation(
        project_id=context.project.id,
        media_asset_id=context.media_asset.id if context.media_asset else None,
        type=edit_type,
        source="assistant_chat",
        start=start,
        end=end,
        enabled=True,
        details=details,
    )
    context.session.add(edit)
    touch_project(context.session, context.project)
    context.session.commit()
    context.session.refresh(edit)
    return edit


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def _list_edits(context: ToolContext, _args: dict[str, Any]) -> ToolResult:
    edits = context.session.exec(
        select(EditOperation)
        .where(EditOperation.project_id == context.project.id)
        .where(EditOperation.type != PROTECTED_EDIT_TYPE)
        .order_by(EditOperation.start)
    ).all()
    return ToolResult(
        data={"edits": [_edit_to_dict(edit) for edit in edits]},
        summary=f"Listed {len(edits)} saved edits.",
    )


def _add_cut(context: ToolContext, args: dict[str, Any]) -> ToolResult:
    start, end = _validate_range(context, args.get("start"), args.get("end"))
    details: dict[str, Any] = {"duration": round(end - start, 3)}
    if args.get("reason"):
        details["reason"] = str(args["reason"])
    edit = _create_edit(context, "cut", start, end, details)
    return ToolResult(
        data={"edit": _edit_to_dict(edit)},
        summary=f"Added cut {start:.1f}s-{end:.1f}s.",
        mutated_edits=True,
    )


def _add_zoom(context: ToolContext, args: dict[str, Any]) -> ToolResult:
    start, end = _validate_range(context, args.get("start"), args.get("end"))
    try:
        zoom_level = float(args.get("zoom_level", 1.2))
    except (TypeError, ValueError):
        raise ToolError("zoom_level must be a number")
    if not MIN_ZOOM_LEVEL < zoom_level <= MAX_ZOOM_LEVEL:
        raise ToolError(
            f"zoom_level must be greater than {MIN_ZOOM_LEVEL} and at most {MAX_ZOOM_LEVEL}"
        )
    details: dict[str, Any] = {"zoom_level": zoom_level}
    if args.get("reason"):
        details["reason"] = str(args["reason"])
    edit = _create_edit(context, "zoom", start, end, details)
    return ToolResult(
        data={"edit": _edit_to_dict(edit)},
        summary=f"Added {zoom_level:.2f}x zoom {start:.1f}s-{end:.1f}s.",
        mutated_edits=True,
    )


def _update_edit(context: ToolContext, args: dict[str, Any]) -> ToolResult:
    edit = _get_agent_editable_edit(context, args.get("edit_id"))
    changed = []

    if args.get("start") is not None or args.get("end") is not None:
        new_start = args.get("start", edit.start)
        new_end = args.get("end", edit.end)
        edit.start, edit.end = _validate_range(context, new_start, new_end)
        changed.append(f"range to {edit.start:.1f}s-{edit.end:.1f}s")

    if args.get("enabled") is not None:
        edit.enabled = bool(args["enabled"])
        changed.append("enabled" if edit.enabled else "disabled")

    if not changed:
        raise ToolError("Provide at least one of: start, end, enabled")

    edit.updated_at = utc_now()
    context.session.add(edit)
    touch_project(context.session, context.project)
    context.session.commit()
    context.session.refresh(edit)
    return ToolResult(
        data={"edit": _edit_to_dict(edit)},
        summary=f"Updated {edit.type} edit: {', '.join(changed)}.",
        mutated_edits=True,
    )


def _delete_edit(context: ToolContext, args: dict[str, Any]) -> ToolResult:
    edit = _get_agent_editable_edit(context, args.get("edit_id"))
    description = f"{edit.type} {edit.start:.1f}s-{edit.end:.1f}s"
    context.session.delete(edit)
    touch_project(context.session, context.project)
    context.session.commit()
    return ToolResult(
        data={"deleted": True, "edit_id": str(args.get("edit_id"))},
        summary=f"Deleted {description}.",
        mutated_edits=True,
    )


def _detect_silence(context: ToolContext, args: dict[str, Any]) -> ToolResult:
    if context.video_path is None:
        raise ToolError("The source video file is not available on the server")
    try:
        min_silence_duration = float(args.get("min_silence_duration", 1.0))
        silence_threshold = int(args.get("silence_threshold", -40))
    except (TypeError, ValueError):
        raise ToolError("min_silence_duration and silence_threshold must be numbers")

    pauses = detect_audio_pauses(
        str(context.video_path),
        min_silence_duration=min_silence_duration,
        silence_threshold=silence_threshold,
    )
    pauses = merge_nearby_pauses(pauses, max_gap=0.5)
    total = get_total_silence_duration(pauses)
    return ToolResult(
        data={"pauses": pauses, "count": len(pauses), "total_silence_duration": total},
        summary=(
            f"Silence detection found {len(pauses)} pauses"
            f" ({total:.1f}s of silence)."
        ),
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_RANGE_PROPERTIES = {
    "start": {"type": "number", "description": "Start time in seconds"},
    "end": {"type": "number", "description": "End time in seconds"},
}

TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in [
        ToolSpec(
            name="list_edits",
            description=(
                "List the project's saved edit operations with their ids, types,"
                " time ranges, and enabled state. Use this to get edit ids before"
                " updating or deleting, or to verify changes."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            handler=_list_edits,
        ),
        ToolSpec(
            name="add_cut",
            description=(
                "Add a cut edit that removes the given time range from the"
                " rendered video."
            ),
            parameters={
                "type": "object",
                "properties": {
                    **_RANGE_PROPERTIES,
                    "reason": {
                        "type": "string",
                        "description": "Short note on why this range is cut",
                    },
                },
                "required": ["start", "end"],
            },
            handler=_add_cut,
            mutates=True,
        ),
        ToolSpec(
            name="add_zoom",
            description="Add a zoom-in effect over the given time range.",
            parameters={
                "type": "object",
                "properties": {
                    **_RANGE_PROPERTIES,
                    "zoom_level": {
                        "type": "number",
                        "description": "Zoom factor, e.g. 1.2 (default). Must be >1 and <=3.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Short note on why this moment is emphasized",
                    },
                },
                "required": ["start", "end"],
            },
            handler=_add_zoom,
            mutates=True,
        ),
        ToolSpec(
            name="update_edit",
            description=(
                "Modify a saved edit: move/resize its time range and/or enable or"
                " disable it. Requires the edit id (see the project state or"
                " list_edits)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "edit_id": {"type": "string", "description": "Id of the edit to change"},
                    "start": {"type": "number", "description": "New start time in seconds"},
                    "end": {"type": "number", "description": "New end time in seconds"},
                    "enabled": {
                        "type": "boolean",
                        "description": "Enable (true) or disable (false) the edit",
                    },
                },
                "required": ["edit_id"],
            },
            handler=_update_edit,
            mutates=True,
        ),
        ToolSpec(
            name="delete_edit",
            description="Permanently delete a saved edit by id.",
            parameters={
                "type": "object",
                "properties": {
                    "edit_id": {"type": "string", "description": "Id of the edit to delete"},
                },
                "required": ["edit_id"],
            },
            handler=_delete_edit,
            mutates=True,
        ),
        ToolSpec(
            name="detect_silence",
            description=(
                "Analyze the source audio and return silent pauses as candidate"
                " cut ranges. Does NOT create any edits; add cuts explicitly if"
                " the user wants them removed."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "min_silence_duration": {
                        "type": "number",
                        "description": "Minimum pause length in seconds (default 1.0)",
                    },
                    "silence_threshold": {
                        "type": "number",
                        "description": "Silence threshold in dBFS (default -40)",
                    },
                },
                "required": [],
            },
            handler=_detect_silence,
        ),
    ]
}


def get_tool_specs() -> list[dict[str, Any]]:
    """Tool definitions in the Groq/OpenAI function-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        }
        for spec in TOOLS.values()
    ]


def execute_tool(name: str, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
    """Run one tool call; failures come back as an unsuccessful ToolResult.

    Args:
        name: Tool name as emitted by the LLM.
        arguments: Parsed JSON arguments from the tool call.
        context: Project/session context to execute against.

    Returns:
        A ToolResult; on failure ``ok`` is False and ``data`` carries the error
        message so the agent loop can hand it back to the model.
    """
    spec = TOOLS.get(name)
    if spec is None:
        return ToolResult(
            data={"error": f"Unknown tool '{name}'"},
            summary=f"Unknown tool '{name}'.",
            ok=False,
        )
    try:
        return spec.handler(context, arguments or {})
    except ToolError as e:
        return ToolResult(
            data={"error": str(e)},
            summary=f"{name} failed: {e}",
            ok=False,
        )
