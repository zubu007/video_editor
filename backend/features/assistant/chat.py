"""
LLM agent for the in-editor project assistant using the Groq Cloud API.

The assistant answers questions about the current project and can act on it
through a small set of registered tools (see tools.py): listing, adding,
updating, and deleting edits, plus silence detection. Tool calls run in an
agentic loop — the model may chain several calls before producing its reply.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from groq import Groq

from backend.features.assistant.tools import (
    ToolContext,
    ToolResult,
    execute_tool,
    get_tool_specs,
)

DEFAULT_MODEL = "llama-3.3-70b-versatile"

# Roles the frontend may send as conversation history.
ALLOWED_ROLES = {"user", "assistant"}

# Keep prompt sizes bounded for long recordings / busy sessions.
MAX_TRANSCRIPT_CHARS = 12000
MAX_ACTIVITY_LINES = 40
MAX_HISTORY_MESSAGES = 30

# Cap on LLM round-trips per user message. Each round may contain several tool
# calls; after the cap a final tool-less call forces a textual reply.
MAX_TOOL_ROUNDS = 5

SYSTEM_PROMPT_TEMPLATE = """You are the editing assistant built into a podcast video editor. \
You help the user understand and work on their current project.

You can see the current project state below, and you have tools to act on the \
project: list edits, add cuts and zooms, move/enable/disable/delete saved \
edits, and detect silences in the audio.

Guidelines:
- Be concise and practical; answer like a helpful co-editor.
- Refer to timestamps in seconds (e.g. "12.4s-15.0s") when talking about moments in the video.
- Use tools when the user asks for a change or an analysis; don't claim to have \
done something without calling the matching tool. After acting, briefly confirm \
what you did.
- Edit ids come from the project state or list_edits — never invent them.
- Only make the changes the user asked for. For sweeping operations (e.g. \
"cut all silences"), you may chain tools: detect first, then add the cuts.
- Some things are not yet available through chat: rearranging timeline \
segments, stock footage, diagrams, captions, and rendering. Point the user to \
the matching editor panel for those.
- If something is not in the project state, say you don't know rather than guessing.

Current project state:
{project_context}"""


@dataclass
class ChatAction:
    """One executed tool call, reported back to the client."""

    tool: str
    summary: str
    ok: bool


@dataclass
class ChatResult:
    """Final assistant reply plus everything the agent did along the way."""

    reply: str
    actions: list[ChatAction] = field(default_factory=list)
    edits_changed: bool = False


class ProjectChatLLM:
    """LLM agent for the in-editor project assistant chat."""

    def __init__(self, api_key: Optional[str] = None, model: str = DEFAULT_MODEL):
        """Initializes the chat client.

        Args:
            api_key: Groq API key. If not provided, reads from the API_KEY env var.
            model: Groq model to use.
        """
        self.api_key = api_key or os.getenv("API_KEY")
        if not self.api_key:
            raise ValueError(
                "Groq API key must be provided either as argument or API_KEY environment variable"
            )

        self.client = Groq(api_key=self.api_key)
        self.model = model

    def chat(
        self,
        messages: list[dict],
        project_context: str,
        tool_context: Optional[ToolContext] = None,
    ) -> ChatResult:
        """Runs the agent loop for one user message.

        Args:
            messages: Conversation history as {"role", "content"} dicts, oldest
                first, ending with the latest user message. Only "user" and
                "assistant" roles are used.
            project_context: Prebuilt description of the current project state
                (media, edits, timeline, activity log, transcript excerpt).
            tool_context: Project/session context for tool execution. When
                None the assistant is conversational only (no tools offered).

        Returns:
            A ChatResult with the reply text, the tool calls that ran, and
            whether any of them changed the project's edits.

        Raises:
            ValueError: If the history contains no user message.
            RuntimeError: If an LLM call fails.
        """
        history = [
            {"role": message["role"], "content": str(message["content"])}
            for message in messages
            if message.get("role") in ALLOWED_ROLES and message.get("content")
        ][-MAX_HISTORY_MESSAGES:]

        if not any(message["role"] == "user" for message in history):
            raise ValueError("Chat history must contain at least one user message")

        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(project_context=project_context)
        conversation: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *history,
        ]
        tools = get_tool_specs() if tool_context is not None else None

        result = ChatResult(reply="")
        for _ in range(MAX_TOOL_ROUNDS):
            message = self._complete(conversation, tools)
            tool_calls = getattr(message, "tool_calls", None)
            if not tool_calls:
                result.reply = self._reply_text(message)
                return result

            conversation.append(self._assistant_turn(message, tool_calls))
            for call in tool_calls:
                tool_result = self._run_tool_call(call, tool_context, result)
                conversation.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(tool_result.data),
                    }
                )

        # Tool budget exhausted: force a plain reply summarizing what happened.
        message = self._complete(conversation, tools=None)
        result.reply = self._reply_text(message)
        return result

    def _complete(self, conversation: list[dict], tools: Optional[list[dict]]):
        """One LLM round-trip; returns the response message object."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": conversation,
            "temperature": 0.4,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        try:
            response = self.client.chat.completions.create(**kwargs)
        except Exception as e:
            raise RuntimeError(f"Error generating chat reply: {e}")
        return response.choices[0].message

    def _run_tool_call(self, call, tool_context: ToolContext, result: ChatResult):
        """Execute one tool call, recording the action on the result."""
        try:
            arguments = self._parse_arguments(call.function.arguments)
        except (ValueError, TypeError):
            arguments = None

        if arguments is None:
            tool_result = ToolResult(
                data={"error": "Tool arguments were not valid JSON"},
                summary=f"{call.function.name} failed: invalid arguments.",
                ok=False,
            )
        else:
            tool_result = execute_tool(call.function.name, arguments, tool_context)

        result.actions.append(
            ChatAction(
                tool=call.function.name,
                summary=tool_result.summary,
                ok=tool_result.ok,
            )
        )
        if tool_result.ok and tool_result.mutated_edits:
            result.edits_changed = True
        return tool_result

    @staticmethod
    def _parse_arguments(raw: Optional[str]) -> dict[str, Any]:
        """Parse tool-call arguments, tolerating LLM encoding quirks.

        Models sometimes emit an empty string, JSON null, or a double-encoded
        JSON string ("\"{}\"") for tools without parameters.
        """
        if raw is None or not raw.strip():
            return {}
        parsed = json.loads(raw)
        if isinstance(parsed, str):
            parsed = json.loads(parsed) if parsed.strip() else {}
        if parsed is None:
            return {}
        if not isinstance(parsed, dict):
            raise ValueError("arguments must be a JSON object")
        return parsed

    @staticmethod
    def _assistant_turn(message, tool_calls) -> dict[str, Any]:
        """Serialize the model's tool-calling turn back into the conversation."""
        return {
            "role": "assistant",
            "content": message.content or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in tool_calls
            ],
        }

    @staticmethod
    def _reply_text(message) -> str:
        content = (message.content or "").strip()
        if not content:
            raise RuntimeError("LLM returned an empty chat reply")
        return content


def build_project_context(
    project_summary: str,
    activity_log: list[str] | None = None,
    transcript_text: str = "",
) -> str:
    """Assembles the project-state block injected into the system prompt.

    Args:
        project_summary: Description of the project's media, edits, and timeline.
        activity_log: Recent editor activity lines (newest last).
        transcript_text: Plain-text transcript of the source video.

    Returns:
        A single formatted context string, with transcript and activity log
        truncated to keep the prompt bounded.
    """
    parts = [project_summary.strip() or "No project details available."]

    if activity_log:
        recent = activity_log[-MAX_ACTIVITY_LINES:]
        parts.append(
            "Recent editor activity (oldest first):\n"
            + "\n".join(f"- {line}" for line in recent)
        )

    transcript_text = transcript_text.strip()
    if transcript_text:
        if len(transcript_text) > MAX_TRANSCRIPT_CHARS:
            transcript_text = (
                transcript_text[:MAX_TRANSCRIPT_CHARS] + "\n[transcript truncated]"
            )
        parts.append(f"Transcript:\n{transcript_text}")
    else:
        parts.append("Transcript: not available yet.")

    return "\n\n".join(parts)


def generate_chat_reply(
    messages: list[dict],
    project_context: str,
    tool_context: Optional[ToolContext] = None,
    api_key: Optional[str] = None,
    model: str = DEFAULT_MODEL,
) -> ChatResult:
    """Convenience wrapper mirroring the other feature modules' entry points.

    Args:
        messages: Conversation history ({"role", "content"} dicts, oldest first).
        project_context: Prebuilt project state description.
        tool_context: Project/session context enabling agent tools (optional).
        api_key: Groq API key (falls back to the API_KEY env var).
        model: Groq model to use.

    Returns:
        The agent's ChatResult (reply text, executed actions, edits_changed).
    """
    client = ProjectChatLLM(api_key=api_key, model=model)
    return client.chat(messages, project_context, tool_context=tool_context)
