"""Tests for the manual streaming text-caption ASS builder."""

from __future__ import annotations


from backend.features.captions.ass_builder import _ass_time
from backend.features.captions.text_caption import (
    build_text_caption_ass,
    _reveal_events,
)

PLAY_RES = (1920, 1080)


def _dialogues(document: str) -> list[str]:
    return [line for line in document.splitlines() if line.startswith("Dialogue:")]


def test_document_has_note_style_and_header():
    document = build_text_caption_ass(
        [{"start": 1.0, "end": 4.0, "text": "Buying Glimmer"}], PLAY_RES
    )
    assert "Style: Note," in document
    assert "PlayResX: 1920" in document
    assert "PlayResY: 1080" in document


def test_typewriter_reveals_growing_prefix_to_full_text():
    text = "Buying Glimmer Cape for the save"
    document = build_text_caption_ass(
        [{"start": 2.0, "end": 6.0, "text": text}], PLAY_RES
    )
    events = _dialogues(document)
    assert len(events) > 1
    # Text after the last comma of each event is a prefix of the full text, and
    # the final event shows all of it, ending exactly at the caption's end.
    shown = [event.split(",,", 1)[1] for event in events]
    assert all(text.startswith(part.split("}")[-1]) for part in shown)
    assert shown[-1].endswith(text)
    assert events[-1].split(",")[2] == _ass_time(6.0)


def test_first_event_starts_at_caption_start():
    document = build_text_caption_ass(
        [{"start": 3.5, "end": 7.0, "text": "Hello there"}], PLAY_RES
    )
    first = _dialogues(document)[0]
    assert first.split(",")[1] == _ass_time(3.5)


def test_position_sets_alignment_tag():
    for position, tag in (("top", r"\an8"), ("middle", r"\an5"), ("bottom", r"\an2")):
        document = build_text_caption_ass(
            [{"start": 0.0, "end": 2.0, "text": "hi", "position": position}], PLAY_RES
        )
        assert tag in document


def test_braces_in_text_are_neutralised():
    # A literal brace would open an ASS override block; it must be escaped.
    events = _reveal_events({"start": 0.0, "end": 2.0, "text": "a{b}c"}, alignment=2)
    body = " ".join(event.split(",,", 1)[1] for event in events)
    assert "{\\an" in events[0]  # the alignment override is intentional
    assert "a(b)c" in body


def test_empty_or_zero_span_caption_is_skipped():
    assert _reveal_events({"start": 1.0, "end": 1.0, "text": "x"}, 2) == []
    assert _reveal_events({"start": 1.0, "end": 3.0, "text": "   "}, 2) == []


def test_reveal_override_bounds_to_span():
    # A reveal longer than the span is clamped so the last event still ends at end.
    document = build_text_caption_ass(
        [{"start": 0.0, "end": 2.0, "text": "abcdefghij", "reveal_seconds": 10.0}],
        PLAY_RES,
    )
    events = _dialogues(document)
    assert events[-1].split(",")[2] == _ass_time(2.0)
