"""Shared LLM provider selection for all Groq/OpenAI-compatible chat clients."""

from backend.features.llm.provider import DEFAULT_MODEL, create_chat_client

__all__ = ["DEFAULT_MODEL", "create_chat_client"]
