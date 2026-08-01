"""Tests for the pluggable K/D/A OCR engine registry and its API surface."""

from __future__ import annotations

import numpy as np
import pytest

from fastapi.testclient import TestClient

from backend.app import app
from backend.features.gaming.ocr import (
    DEFAULT_OCR_ENGINE,
    OCR_ENGINES,
    engine_available,
    list_engines,
    read_digits,
)

# ---------------------------------------------------------------- registry


def test_default_engine_is_registered():
    assert DEFAULT_OCR_ENGINE in OCR_ENGINES


def test_list_engines_covers_registry_with_availability():
    engines = {e["name"]: e for e in list_engines()}
    assert set(engines) == set(OCR_ENGINES)
    for entry in engines.values():
        assert isinstance(entry["available"], bool)
        assert entry["label"] and entry["description"] and entry["detail"]


def test_engine_available_rejects_unknown_engine():
    with pytest.raises(ValueError, match="Unknown OCR engine"):
        engine_available("not-an-ocr")


def test_read_digits_rejects_unknown_engine():
    with pytest.raises(ValueError, match="Unknown OCR engine"):
        read_digits("not-an-ocr", np.zeros((10, 10), np.uint8))


def test_read_digits_swallows_engine_failures(monkeypatch):
    # A bad read must degrade to "no read" (empty string), not kill the scan.
    import backend.features.gaming.ocr as ocr_module

    monkeypatch.setitem(
        ocr_module._READ_FUNCS,
        "tesseract",
        lambda bw: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert read_digits("tesseract", np.zeros((10, 10), np.uint8)) == ""


def test_paddle_texts_parses_both_result_shapes():
    from backend.features.gaming.ocr import _paddle_texts

    # PaddleOCR 3.x predict(): dict-like pages with rec_texts.
    assert _paddle_texts([{"rec_texts": ["3/1/5"]}]) == ["3/1/5"]
    # PaddleOCR 2.x ocr(): pages of [box, (text, confidence)] lines.
    assert _paddle_texts([[[[0, 0, 1, 1], ("3/1/5", 0.99)]]]) == ["3/1/5"]
    assert _paddle_texts(None) == []


# ---------------------------------------------------------------- API


def test_ocr_engines_endpoint_lists_registry():
    client = TestClient(app)
    response = client.get("/api/gaming/ocr-engines")
    assert response.status_code == 200
    payload = response.json()
    assert payload["default"] == DEFAULT_OCR_ENGINE
    assert {e["name"] for e in payload["engines"]} == set(OCR_ENGINES)


def test_detect_deaths_rejects_unknown_ocr_engine():
    client = TestClient(app)
    response = client.post("/api/gaming/detect-deaths/some-file?ocr_engine=not-an-ocr")
    assert response.status_code == 400
    assert "Unknown OCR engine" in response.json()["detail"]
