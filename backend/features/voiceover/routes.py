"""API routes exposing Voice Studio connection state and voices."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from backend.features.voiceover.client import VoiceStudioClient, VoiceStudioError

router = APIRouter(prefix="/api/voiceover", tags=["voiceover"])


@router.get("/capabilities")
def get_capabilities() -> dict[str, Any]:
    """Report connection state; generation is not implemented yet."""
    return {**VoiceStudioClient().status(), "generation_available": False}


@router.get("/voices")
def get_voices() -> dict[str, Any]:
    """List profile voices from the configured Voice Studio server."""
    client = VoiceStudioClient()
    if not client.settings.enabled:
        raise HTTPException(503, "VOICEOVER_PROVIDER is not 'voice_studio'")
    try:
        return {"voices": client.voices()}
    except VoiceStudioError as exc:
        raise HTTPException(503, str(exc)) from exc
