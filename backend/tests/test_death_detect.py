"""Tests for the Dota 2 death/alive interval detector.

The pure signal/geometry functions are tested directly; the full pipeline
integration test is gated on the (large, un-committed) sample recording being
present and ``DEATH_DETECT_SLOW`` being set, since it decodes a whole match.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from backend.features.gaming.death_detect import (
    DotaHudLayout,
    _colour_signature,
    _death_event_times,
    _death_intervals_from_runs,
    _match_slot,
    _ocr_kda,
    _respawn_signal,
    _signal_runs,
    detect_death_intervals,
)


def _block(bgr: tuple[int, int, int], size: int = 24) -> np.ndarray:
    img = np.zeros((size, size, 3), np.uint8)
    img[:, :] = bgr
    return img


# ---------------------------------------------------------------- layout


def test_strip_height_is_even():
    # ffmpeg snaps odd crop heights to even; an odd strip desyncs the reader.
    assert DotaHudLayout().strip_height % 2 == 0


def test_scaled_layout_scales_coordinates():
    lay = DotaHudLayout().scaled(1280, 720)
    assert (lay.width, lay.height) == (1280, 720)
    assert lay.radiant_centers[0] == round(564 * 1280 / 1920)
    assert lay.strip_height % 2 == 0


def test_scaled_is_identity_at_native_resolution():
    lay = DotaHudLayout()
    assert lay.scaled(1920, 1080) is lay


def test_respawn_box_brackets_the_slot():
    lay = DotaHudLayout()
    x0, y0, x1, y1 = lay.respawn_box(816)
    assert x0 < 816 < x1 and y0 < y1


# ---------------------------------------------------------------- colour match


def test_colour_signature_is_normalised():
    sig = _colour_signature(_block((0, 0, 255)))  # saturated red
    assert abs(float(sig.sum()) - 1.0) < 1e-6


def test_colour_signature_masks_dark_pixels():
    # A black crop has no saturated/bright pixels, so the signature is empty.
    assert float(_colour_signature(np.zeros((24, 24, 3), np.uint8)).sum()) == 0.0


def test_match_slot_picks_the_matching_colour():
    bottom = _colour_signature(_block((255, 0, 0)))  # blue
    slots = [
        _colour_signature(_block((0, 0, 255))),  # red
        _colour_signature(_block((0, 255, 0))),  # green
        _colour_signature(_block((255, 0, 0))),  # blue <- match
    ]
    slot, margin = _match_slot(bottom, slots)
    assert slot == 2
    assert margin > 0


# ---------------------------------------------------------------- runs / events


def test_signal_runs_extracts_thresholded_runs():
    times = list(range(10))
    signal = [0, 0, 0.1, 0.1, 0.1, 0, 0, 0.1, 0.1, 0]
    runs = _signal_runs(times, signal, threshold=0.05, min_samples=2)
    assert [(r["start"], r["end"]) for r in runs] == [(2, 5), (7, 9)]


def test_signal_runs_drops_too_short_runs():
    times = list(range(5))
    signal = [0, 0.2, 0, 0, 0]  # single sample, below min_samples
    assert _signal_runs(times, signal, threshold=0.05, min_samples=2) == []


def test_ocr_kda_rejects_dips_and_implausible_jumps(monkeypatch):
    import pytesseract

    # From a running (3, 1, 5): a dip below current, then a valid +1 assist, then
    # an implausible assists jump (> +3 per sample). Only the middle read sticks.
    reads = iter(["2/0/4", "3/1/6", "3/1/20"])
    monkeypatch.setattr(pytesseract, "image_to_string", lambda *a, **k: next(reads))
    img = np.zeros((20, 210, 3), np.uint8)

    prev = _ocr_kda(img, (3, 1, 5))  # values can't decrease → rejected
    assert prev == (3, 1, 5)
    prev = _ocr_kda(img, prev)  # +1 assist → accepted
    assert prev == (3, 1, 6)
    prev = _ocr_kda(img, prev)  # +14 assists is noise → rejected
    assert prev == (3, 1, 6)


def test_death_event_times_finds_increments():
    times = [0, 1, 2, 3, 4]
    deaths = [0, 0, 1, 1, 2]
    assert _death_event_times(deaths, times) == [2, 4]


def test_death_intervals_use_ocr_start_and_respawn_end():
    # Respawn box gives the reliable window; the deaths-counter increment (a
    # couple of seconds inside the match window) pins the start, the box the end.
    runs = [{"start": 100.0, "end": 110.0}, {"start": 200.0, "end": 214.0}]
    intervals = _death_intervals_from_runs(runs, [102.0, 199.0])
    assert intervals == [
        {"start": 102.0, "end": 110.0},  # OCR start replaces the respawn start
        {"start": 199.0, "end": 214.0},
    ]


def test_death_intervals_keep_respawn_start_without_a_match():
    # No OCR increment (tesseract off) or none within the match window → the
    # respawn-box start is kept so the death is still cut.
    runs = [{"start": 100.0, "end": 110.0}]
    assert _death_intervals_from_runs(runs, []) == [{"start": 100.0, "end": 110.0}]
    far = _death_intervals_from_runs(runs, [50.0])  # outside _DEATH_MATCH_WINDOW
    assert far == [{"start": 100.0, "end": 110.0}]


def test_death_intervals_consume_each_increment_once():
    # Two close deaths must not both snap to the same increment.
    runs = [{"start": 100.0, "end": 106.0}, {"start": 107.0, "end": 113.0}]
    intervals = _death_intervals_from_runs(runs, [101.0, 108.0])
    assert intervals == [
        {"start": 101.0, "end": 106.0},
        {"start": 108.0, "end": 113.0},
    ]


# ---------------------------------------------------------------- respawn signal


def test_respawn_signal_high_on_gold_low_on_empty():
    lay = DotaHudLayout()
    center = lay.radiant_centers[4]
    x0, y0, x1, y1 = lay.respawn_box(center)

    gold = np.zeros((lay.strip_height, lay.width, 3), np.uint8)
    gold[y0:y1, x0:x1] = (0, 180, 255)  # BGR orange/gold -> hue ~21
    assert _respawn_signal(gold, center, lay) > 0.5

    empty = np.zeros((lay.strip_height, lay.width, 3), np.uint8)
    assert _respawn_signal(empty, center, lay) == 0.0


# ---------------------------------------------------------------- integration


_SAMPLE = Path("backend/sample_video/2026-07-26 15-28-10.mp4")


@pytest.mark.skipif(
    not (_SAMPLE.exists() and os.environ.get("DEATH_DETECT_SLOW")),
    reason="sample video absent or DEATH_DETECT_SLOW unset (decodes a full match)",
)
def test_detect_on_sample_video():
    intervals = detect_death_intervals(str(_SAMPLE))
    # Three solid deaths were confirmed by frame inspection of the sample.
    assert len(intervals) == 3
    assert all(iv["duration"] >= 5.0 for iv in intervals)
    starts = [round(iv["start"]) for iv in intervals]
    assert starts == sorted(starts)
