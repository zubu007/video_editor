"""Tests for the project assistant agent: tool execution and the chat loop."""

import json
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from backend.features.assistant.chat import ProjectChatLLM
from backend.features.assistant.tools import (
    ToolContext,
    execute_tool,
    get_tool_specs,
)
from backend.storage.database import EditOperation, MediaAsset, Project


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture()
def context(session):
    project = Project(name="Agent Test Project")
    session.add(project)
    session.commit()
    session.refresh(project)

    asset = MediaAsset(
        project_id=project.id,
        file_id="file-123",
        filename="video.mp4",
        file_url="/api/video/file-123",
        size=1000,
        duration=60.0,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)

    return ToolContext(session=session, project=project, media_asset=asset)


def test_tool_specs_are_valid_function_schemas():
    specs = get_tool_specs()
    names = {spec["function"]["name"] for spec in specs}
    assert {"list_edits", "add_cut", "add_zoom", "update_edit", "delete_edit"} <= names
    for spec in specs:
        assert spec["type"] == "function"
        assert spec["function"]["parameters"]["type"] == "object"


def test_add_cut_creates_edit(context):
    result = execute_tool("add_cut", {"start": 1.0, "end": 2.5, "reason": "dead air"}, context)
    assert result.ok and result.mutated_edits
    edit = context.session.get(EditOperation, result.data["edit"]["id"])
    assert edit.type == "cut"
    assert edit.source == "assistant_chat"
    assert edit.details["reason"] == "dead air"


def test_add_cut_rejects_range_past_video_end(context):
    result = execute_tool("add_cut", {"start": 50.0, "end": 90.0}, context)
    assert not result.ok
    assert "60.0s" in result.data["error"]


def test_add_cut_rejects_inverted_range(context):
    result = execute_tool("add_cut", {"start": 5.0, "end": 2.0}, context)
    assert not result.ok


def test_add_zoom_validates_level(context):
    result = execute_tool("add_zoom", {"start": 0, "end": 3, "zoom_level": 9}, context)
    assert not result.ok

    result = execute_tool("add_zoom", {"start": 0, "end": 3, "zoom_level": 1.5}, context)
    assert result.ok
    assert result.data["edit"]["details"]["zoom_level"] == 1.5


def test_update_edit_moves_and_disables(context):
    created = execute_tool("add_cut", {"start": 1.0, "end": 2.0}, context)
    edit_id = created.data["edit"]["id"]

    result = execute_tool(
        "update_edit", {"edit_id": edit_id, "start": 3.0, "end": 4.0, "enabled": False}, context
    )
    assert result.ok and result.mutated_edits
    edit = context.session.get(EditOperation, edit_id)
    assert (edit.start, edit.end, edit.enabled) == (3.0, 4.0, False)


def test_update_edit_requires_changes(context):
    created = execute_tool("add_cut", {"start": 1.0, "end": 2.0}, context)
    result = execute_tool("update_edit", {"edit_id": created.data["edit"]["id"]}, context)
    assert not result.ok


def test_delete_edit_removes_row(context):
    created = execute_tool("add_cut", {"start": 1.0, "end": 2.0}, context)
    edit_id = created.data["edit"]["id"]
    result = execute_tool("delete_edit", {"edit_id": edit_id}, context)
    assert result.ok and result.mutated_edits
    assert context.session.get(EditOperation, edit_id) is None


def test_timeline_segments_are_protected(context):
    segment = EditOperation(
        project_id=context.project.id,
        type="timeline_segment",
        source="timeline",
        start=0.0,
        end=10.0,
        details={"position": 0},
    )
    context.session.add(segment)
    context.session.commit()
    context.session.refresh(segment)

    for tool in ("update_edit", "delete_edit"):
        result = execute_tool(tool, {"edit_id": segment.id, "enabled": False}, context)
        assert not result.ok
        assert "chat" in result.data["error"]

    listed = execute_tool("list_edits", {}, context)
    assert listed.data["edits"] == []


def test_unknown_edit_and_unknown_tool(context):
    result = execute_tool("delete_edit", {"edit_id": "nope"}, context)
    assert not result.ok

    result = execute_tool("not_a_tool", {}, context)
    assert not result.ok


def test_detect_silence_needs_video_file(context):
    result = execute_tool("detect_silence", {}, context)
    assert not result.ok
    assert "not available" in result.data["error"]


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------


def _message(content=None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def _tool_call(call_id, name, arguments):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


class FakeCompletions:
    """Returns queued responses and records every request payload."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        message = self.responses.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def make_agent(responses):
    agent = ProjectChatLLM(api_key="test-key")
    completions = FakeCompletions(responses)
    agent.client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    return agent, completions


def test_chat_plain_reply_without_tools(context):
    agent, completions = make_agent([_message(content="Just an answer.")])
    result = agent.chat(
        [{"role": "user", "content": "hi"}], "context", tool_context=context
    )
    assert result.reply == "Just an answer."
    assert result.actions == []
    assert not result.edits_changed
    # Tools were offered to the model
    assert "tools" in completions.requests[0]


def test_chat_executes_tool_calls_and_reports_actions(context):
    agent, completions = make_agent(
        [
            _message(tool_calls=[_tool_call("c1", "add_cut", {"start": 1, "end": 2})]),
            _message(content="Done - cut added."),
        ]
    )
    result = agent.chat(
        [{"role": "user", "content": "cut 1s to 2s"}], "context", tool_context=context
    )
    assert result.reply == "Done - cut added."
    assert [action.tool for action in result.actions] == ["add_cut"]
    assert result.actions[0].ok
    assert result.edits_changed

    # The tool result went back to the model as a tool message.
    second_request = completions.requests[1]
    tool_messages = [m for m in second_request["messages"] if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_call_id"] == "c1"
    assert json.loads(tool_messages[0]["content"])["edit"]["type"] == "cut"

    # And the edit really exists.
    listed = execute_tool("list_edits", {}, context)
    assert len(listed.data["edits"]) == 1


def test_chat_failed_tool_is_reported_but_not_fatal(context):
    agent, _ = make_agent(
        [
            _message(tool_calls=[_tool_call("c1", "add_cut", {"start": 5, "end": 2})]),
            _message(content="That range was invalid."),
        ]
    )
    result = agent.chat(
        [{"role": "user", "content": "cut"}], "context", tool_context=context
    )
    assert not result.actions[0].ok
    assert not result.edits_changed
    assert result.reply == "That range was invalid."


def test_chat_tool_round_budget_forces_reply(context):
    # The model asks for list_edits forever; after the budget a tool-less call
    # must produce the final reply.
    looping = [
        _message(tool_calls=[_tool_call(f"c{i}", "list_edits", {})]) for i in range(5)
    ]
    agent, completions = make_agent([*looping, _message(content="Summary.")])
    result = agent.chat(
        [{"role": "user", "content": "loop"}], "context", tool_context=context
    )
    assert result.reply == "Summary."
    assert len(result.actions) == 5
    # Final request must not offer tools.
    assert "tools" not in completions.requests[-1]


def test_chat_tolerates_quirky_tool_argument_encodings(context):
    # Models emit "", null, or double-encoded JSON for no-parameter tools.
    calls = [
        SimpleNamespace(id=f"c{i}", function=SimpleNamespace(name="list_edits", arguments=raw))
        for i, raw in enumerate(["", "null", '"{}"', None])
    ]
    agent, _ = make_agent([_message(tool_calls=calls), _message(content="ok")])
    result = agent.chat(
        [{"role": "user", "content": "list"}], "context", tool_context=context
    )
    assert all(action.ok for action in result.actions)
    assert len(result.actions) == 4


def test_chat_without_tool_context_offers_no_tools(context):
    agent, completions = make_agent([_message(content="Chat only.")])
    result = agent.chat([{"role": "user", "content": "hi"}], "context")
    assert result.reply == "Chat only."
    assert "tools" not in completions.requests[0]
