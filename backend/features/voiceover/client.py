"""Read-only HTTP client for a remote Voice Studio server.

Only discovery endpoints are used here (health, engines, voices). Speech
generation is intentionally not implemented yet, so nothing is synthesised and
no models are downloaded or loaded by this module.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from backend.features.voiceover.config import VoiceStudioSettings, load_settings

logger = logging.getLogger(__name__)


class VoiceStudioError(RuntimeError):
    """Raised when the Voice Studio server is unreachable or refuses a request."""


class VoiceStudioClient:
    """Minimal discovery client; the API key is attached server-side only."""

    def __init__(self, settings: VoiceStudioSettings | None = None) -> None:
        self.settings = settings or load_settings()

    def _headers(self) -> dict[str, str]:
        if self.settings.api_key:
            return {"Authorization": f"Bearer {self.settings.api_key}"}
        return {}

    def _get(self, path: str) -> Any:
        url = f"{self.settings.base_url}{path}"
        try:
            response = requests.get(
                url,
                headers=self._headers(),
                timeout=(self.settings.connect_timeout, 30.0),
            )
        except requests.RequestException as exc:
            raise VoiceStudioError(
                f"Cannot reach Voice Studio at {self.settings.base_url}: "
                f"{type(exc).__name__}"
            ) from exc
        if response.status_code in (401, 403):
            raise VoiceStudioError(
                f"Voice Studio refused the request ({response.status_code}); "
                "check VOICE_STUDIO_API_KEY."
            )
        if not response.ok:
            raise VoiceStudioError(
                f"Voice Studio {path} returned HTTP {response.status_code}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise VoiceStudioError(
                f"Voice Studio {path} returned invalid JSON"
            ) from exc

    def health(self) -> Any:
        """Return the server's /health payload."""
        return self._get("/health")

    def engines(self) -> Any:
        """Return the TTS engine inventory."""
        return self._get("/engines")

    def voices(self) -> list[dict[str, Any]]:
        """Return selectable profile voices, hiding OpenAI-style aliases."""
        payload = self._get("/v1/audio/voices")
        voices = payload.get("voices", []) if isinstance(payload, dict) else []
        return [v for v in voices if v.get("type") != "openai_alias"]

    def status(self) -> dict[str, Any]:
        """Summarise connection state without ever raising."""
        settings = self.settings
        result: dict[str, Any] = {
            "provider": settings.provider,
            "enabled": settings.enabled,
            "base_url": settings.base_url,
            "model_configured": settings.model is not None,
            "api_key_configured": settings.api_key is not None,
            "reachable": False,
            "error": None,
        }
        if not settings.enabled:
            result["error"] = "VOICEOVER_PROVIDER is not 'voice_studio'"
            return result
        try:
            self.health()
            result["reachable"] = True
        except VoiceStudioError as exc:
            logger.warning("Voice Studio unavailable: %s", exc)
            result["error"] = str(exc)
        return result
