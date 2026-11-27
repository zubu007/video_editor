"""Environment-driven settings for the remote Voice Studio connection."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_BASE_URL = "http://127.0.0.1:3900"
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_GENERATION_TIMEOUT = 600.0


@dataclass(frozen=True)
class VoiceStudioSettings:
    """Connection settings for a Voice Studio server (never sent to the browser)."""

    provider: str
    base_url: str
    api_key: str | None
    model: str | None
    connect_timeout: float
    generation_timeout: float

    @property
    def enabled(self) -> bool:
        """Whether the voice_studio provider is selected."""
        return self.provider == "voice_studio"


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {raw!r}")
    return value


def load_settings() -> VoiceStudioSettings:
    """Read Voice Studio settings from the environment."""
    return VoiceStudioSettings(
        provider=os.getenv("VOICEOVER_PROVIDER", "disabled").strip().lower(),
        base_url=(os.getenv("VOICE_STUDIO_BASE_URL", "").strip() or DEFAULT_BASE_URL)
        .rstrip("/")
        .removesuffix("/v1"),
        api_key=os.getenv("VOICE_STUDIO_API_KEY", "").strip() or None,
        model=os.getenv("VOICE_STUDIO_MODEL", "").strip() or None,
        connect_timeout=_float_env(
            "VOICE_STUDIO_CONNECT_TIMEOUT", DEFAULT_CONNECT_TIMEOUT
        ),
        generation_timeout=_float_env(
            "VOICE_STUDIO_GENERATION_TIMEOUT", DEFAULT_GENERATION_TIMEOUT
        ),
    )
