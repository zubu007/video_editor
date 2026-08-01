"""Chat-client factory shared by every LLM feature (plan, diagrams, assistant).

The app historically talked to Groq Cloud only. To let the user point the app
at any OpenAI-compatible provider (OpenRouter, Together, a local Ollama/vLLM,
OpenAI itself, ...) from the Settings panel, all three LLM clients build their
client here instead of constructing ``Groq(...)`` directly.

Resolution order for both values is: explicit argument (per-request, from the
frontend settings) → environment variable → default. When a base URL is set the
``openai`` client is used against it (the URL should be the provider's
OpenAI-compatible root, e.g. ``https://api.groq.com/openai/v1`` or
``http://localhost:11434/v1``); with no base URL the Groq SDK and its default
endpoint are used, preserving the original behaviour. Both SDKs expose the same
``client.chat.completions.create(...)`` surface, so callers don't care which
they get.

Environment:
    API_KEY: Default API key (Groq key in the stock setup).
    API_BASE_URL: Optional OpenAI-compatible base URL enabling the custom
        provider path server-wide.
"""

from __future__ import annotations

import os
from typing import Optional

DEFAULT_MODEL = "llama-3.3-70b-versatile"


def create_chat_client(api_key: Optional[str] = None, base_url: Optional[str] = None):
    """Build a chat-completions client for the configured LLM provider.

    Args:
        api_key: Provider API key; falls back to the ``API_KEY`` env var.
        base_url: OpenAI-compatible base URL; falls back to the
            ``API_BASE_URL`` env var. Empty/whitespace values are treated as
            unset. When unset, the Groq SDK with its default endpoint is used.

    Returns:
        A client exposing ``chat.completions.create`` (``openai.OpenAI`` for a
        custom base URL, otherwise ``groq.Groq``).

    Raises:
        ValueError: If no API key is available from either source.
    """
    key = api_key or os.getenv("API_KEY")
    if not key:
        raise ValueError(
            "LLM API key must be provided either as argument or API_KEY "
            "environment variable"
        )

    url = (base_url or os.getenv("API_BASE_URL") or "").strip() or None
    if url:
        from openai import OpenAI

        return OpenAI(api_key=key, base_url=url)

    from groq import Groq

    return Groq(api_key=key)
