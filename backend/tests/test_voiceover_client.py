"""Tests for the Voice Studio connection client."""

from __future__ import annotations

import pytest
import requests

from backend.features.voiceover import client as client_module
from backend.features.voiceover.client import VoiceStudioClient, VoiceStudioError
from backend.features.voiceover.config import VoiceStudioSettings, load_settings


def _settings(**overrides) -> VoiceStudioSettings:
    base = dict(
        provider="voice_studio",
        base_url="http://win-pc:3900",
        api_key="secret",
        model=None,
        connect_timeout=1.0,
        generation_timeout=10.0,
    )
    base.update(overrides)
    return VoiceStudioSettings(**base)


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self.ok = status < 400
        self._payload = payload

    def json(self):
        return self._payload


def test_load_settings_strips_v1_and_defaults(monkeypatch):
    monkeypatch.delenv("VOICEOVER_PROVIDER", raising=False)
    monkeypatch.setenv("VOICE_STUDIO_BASE_URL", "http://host:3900/v1/")
    settings = load_settings()
    assert settings.base_url == "http://host:3900"
    assert not settings.enabled


def test_voices_hide_aliases_and_send_bearer(monkeypatch):
    seen = {}

    def fake_get(url, headers, timeout):
        seen.update(url=url, headers=headers)
        return _Resp(
            payload={
                "voices": [
                    {"voice_id": "a", "type": "openai_alias"},
                    {"voice_id": "b", "type": "profile"},
                ]
            }
        )

    monkeypatch.setattr(client_module.requests, "get", fake_get)
    voices = VoiceStudioClient(_settings()).voices()
    assert [v["voice_id"] for v in voices] == ["b"]
    assert seen["url"] == "http://win-pc:3900/v1/audio/voices"
    assert seen["headers"] == {"Authorization": "Bearer secret"}


def test_status_unreachable_does_not_raise_or_leak_key(monkeypatch):
    def boom(*args, **kwargs):
        raise requests.ConnectionError("nope")

    monkeypatch.setattr(client_module.requests, "get", boom)
    status = VoiceStudioClient(_settings()).status()
    assert status["reachable"] is False
    assert "secret" not in str(status)


def test_auth_refusal_raises(monkeypatch):
    monkeypatch.setattr(
        client_module.requests, "get", lambda *a, **k: _Resp(status=401)
    )
    with pytest.raises(VoiceStudioError, match="VOICE_STUDIO_API_KEY"):
        VoiceStudioClient(_settings()).health()
