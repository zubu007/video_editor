"""Tests for the shorts-style captions feature (layout, ASS building, burn)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import imageio_ffmpeg
import pytest
from moviepy import VideoFileClip

from backend.features.captions.ass_builder import _ass_colour, _ass_time, build_ass
from backend.features.captions.burn import add_captions
from backend.features.captions.layout import group_words
from backend.features.captions.remap import output_intervals, remap_words
from backend.features.captions.styles import (
    FONT_FILES,
    FONTS_DIR,
    STYLE_PRESETS,
    get_style,
)

WORDS = [
    {"start": 0.10, "end": 0.35, "word": " This"},
    {"start": 0.35, "end": 0.55, "word": "is"},
    {"start": 0.55, "end": 0.90, "word": "great."},
    {"start": 1.00, "end": 1.30, "word": "Really"},
    {"start": 1.30, "end": 1.60, "word": "great"},
]


# ---------------------------------------------------------------- layout


def test_group_words_breaks_on_max_words():
    words = [
        {"start": i * 0.3, "end": i * 0.3 + 0.25, "word": f"w{i}"} for i in range(7)
    ]
    pages = group_words(words, max_words=3)
    assert [len(p["words"]) for p in pages] == [3, 3, 1]


def test_group_words_breaks_on_sentence_punctuation():
    pages = group_words(WORDS, max_words=10)
    assert [w["word"] for w in pages[0]["words"]] == ["This", "is", "great."]
    assert [w["word"] for w in pages[1]["words"]] == ["Really", "great"]


def test_group_words_breaks_on_gap():
    words = [
        {"start": 0.0, "end": 0.3, "word": "before"},
        {"start": 2.0, "end": 2.3, "word": "after"},
    ]
    pages = group_words(words, max_gap=1.0)
    assert len(pages) == 2


def test_group_words_strips_and_drops_empty():
    words = [
        {"start": 0.0, "end": 0.2, "word": "  spaced "},
        {"start": 0.2, "end": 0.4, "word": "   "},
    ]
    pages = group_words(words)
    assert len(pages) == 1
    assert pages[0]["words"][0]["word"] == "spaced"
    assert len(pages[0]["words"]) == 1


def test_pages_extend_to_next_page_within_linger():
    # 0.1s gap between "great." and "Really" is within the 0.5s linger, so the
    # first page holds until the second starts (no flicker between pages).
    pages = group_words(WORDS, max_words=3, linger=0.5)
    assert pages[0]["end"] == pytest.approx(pages[1]["start"])
    # The final page lingers past its last word.
    assert pages[-1]["end"] == pytest.approx(1.6 + 0.5)


# ---------------------------------------------------------------- remap


def test_output_intervals_identity_without_cuts():
    intervals = output_intervals(10.0)
    assert intervals == [{"source_start": 0.0, "source_end": 10.0, "output_start": 0.0}]


def test_output_intervals_offsets_after_cuts():
    intervals = output_intervals(
        10.0, [{"start": 1.0, "end": 2.0}, {"start": 3.0, "end": 4.0}]
    )
    assert intervals == [
        {"source_start": 0.0, "source_end": 1.0, "output_start": 0.0},
        {"source_start": 2.0, "source_end": 3.0, "output_start": 1.0},
        {"source_start": 4.0, "source_end": 10.0, "output_start": 2.0},
    ]


def test_output_intervals_follow_timeline_order_and_clamp_to_duration():
    intervals = output_intervals(
        6.0, segments=[{"start": 5.0, "end": 7.0}, {"start": 0.0, "end": 2.0}]
    )
    assert intervals == [
        {"source_start": 5.0, "source_end": 6.0, "output_start": 0.0},
        {"source_start": 0.0, "source_end": 2.0, "output_start": 1.0},
    ]


def test_remap_words_shifts_words_past_cuts_and_drops_cut_words():
    intervals = output_intervals(10.0, [{"start": 1.0, "end": 2.0}])
    words = [
        {"start": 0.2, "end": 0.6, "word": "kept"},
        {"start": 1.2, "end": 1.6, "word": "removed"},
        {"start": 2.2, "end": 2.6, "word": "shifted"},
    ]
    remapped = remap_words(words, intervals)
    assert remapped == [
        {"start": 0.2, "end": 0.6, "word": "kept"},
        {"start": pytest.approx(1.2), "end": pytest.approx(1.6), "word": "shifted"},
    ]


def test_remap_words_clamps_word_straddling_a_cut():
    intervals = output_intervals(10.0, [{"start": 1.0, "end": 2.0}])
    # Midpoint inside the cut: dropped.
    assert remap_words([{"start": 0.8, "end": 1.4, "word": "gone"}], intervals) == []
    # Midpoint kept: the end is clamped to the surviving span.
    remapped = remap_words([{"start": 0.5, "end": 1.3, "word": "edge"}], intervals)
    assert remapped == [{"start": 0.5, "end": 1.0, "word": "edge"}]


def test_remap_words_sorts_by_output_time_for_reordered_segments():
    intervals = output_intervals(
        10.0, segments=[{"start": 5.0, "end": 7.0}, {"start": 0.0, "end": 2.0}]
    )
    words = [
        {"start": 0.5, "end": 1.0, "word": "second"},
        {"start": 5.5, "end": 6.0, "word": "first"},
    ]
    assert [w["word"] for w in remap_words(words, intervals)] == ["first", "second"]


# ---------------------------------------------------------------- ASS builder


def test_ass_colour_is_bgr():
    assert _ass_colour("#FFD900") == "&H0000D9FF"
    assert _ass_colour("#FFFFFF") == "&H00FFFFFF"
    with pytest.raises(ValueError):
        _ass_colour("#FFF")


def test_ass_time_format():
    assert _ass_time(0) == "0:00:00.00"
    assert _ass_time(3661.25) == "1:01:01.25"
    assert _ass_time(-1) == "0:00:00.00"


def test_build_ass_one_event_per_word_for_highlight_styles():
    pages = group_words(WORDS)
    document = build_ass(pages, get_style("bold-pop"), (1080, 1920))
    events = [line for line in document.splitlines() if line.startswith("Dialogue:")]
    assert len(events) == len(WORDS)
    # The active word carries the highlight colour and a pop animation.
    assert r"\c&H0000D9FF" in events[0]
    assert r"\t(0,70,\fscx118\fscy118)" in events[0]
    # Uppercase preset capitalises the text.
    assert "GREAT." in events[0]
    assert "great." not in events[0]


def test_build_ass_single_event_per_page_for_minimal():
    pages = group_words(WORDS, max_words=get_style("minimal").max_words_per_line)
    document = build_ass(pages, get_style("minimal"), (1080, 1920))
    events = [line for line in document.splitlines() if line.startswith("Dialogue:")]
    assert len(events) == len(pages)
    # Mixed-case preset keeps the original casing and adds no override tags.
    assert "This is great." in events[0]
    assert "\\c&H" not in events[0]


def test_build_ass_rainbow_cycles_word_colours():
    pages = group_words(WORDS[:3])
    document = build_ass(pages, get_style("rainbow"), (1080, 1920))
    style = get_style("rainbow")
    for colour in style.word_colours[: len(WORDS[:3])]:
        assert _ass_colour(colour) in document


def test_build_ass_scales_to_frame():
    pages = group_words(WORDS[:2])
    style = get_style("bold-pop")
    document = build_ass(pages, style, (1080, 1920))
    assert "PlayResX: 1080" in document
    assert "PlayResY: 1920" in document
    assert f",{round(1920 * style.font_scale)}," in document


def test_unknown_style_raises_value_error():
    with pytest.raises(ValueError, match="Unknown caption style"):
        get_style("nope")


def test_bundled_fonts_exist():
    for filename in FONT_FILES.values():
        assert (FONTS_DIR / filename).exists(), f"missing bundled font {filename}"


# ---------------------------------------------------------------- burn (integration)


def _encode_black_fixture(path: Path, seconds: float = 3.0) -> None:
    """Encode a tiny all-black test video (any caption pixel is detectable)."""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    command = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=black:duration={seconds}:rate=30:size=320x568",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    subprocess.run(command, check=True, capture_output=True, timeout=120)


@pytest.mark.parametrize("style", sorted(STYLE_PRESETS))
def test_add_captions_draws_text(tmp_path: Path, style: str):
    source = tmp_path / "source.mp4"
    output = tmp_path / f"captioned_{style}.mp4"
    _encode_black_fixture(source)

    add_captions(source, WORDS, output, style=style)

    assert output.exists()
    clip = VideoFileClip(str(output))
    try:
        assert (clip.w, clip.h) == (320, 568)
        # Caption pixels are bright on the black frame while words are spoken...
        assert clip.get_frame(0.5).max() > 100
        # ...and gone after the last page's linger expires (1.6s + 0.5s).
        assert clip.get_frame(2.8).max() < 40
    finally:
        clip.close()


def test_add_captions_rejects_empty_words(tmp_path: Path):
    source = tmp_path / "source.mp4"
    _encode_black_fixture(source, seconds=1.0)
    with pytest.raises(ValueError, match="No caption words"):
        add_captions(source, [], tmp_path / "out.mp4")
