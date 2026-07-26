"""Manual "streaming" text captions burned in with a typewriter reveal.

Unlike the transcript-driven shorts captions in :mod:`ass_builder`, these are
notes the editor places by hand at a chosen moment (a thought, an item choice)
and that stream onto the screen character-by-character. Each caption is a
free-text block ``{"start", "end", "text"}`` positioned over the video; the
reveal is produced the same way ``ass_builder`` animates words — a sequence of
Dialogue events, each showing a longer prefix of the text — which libass renders
natively.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

from backend.features.captions.ass_builder import _ass_colour, _ass_time, _escape_text
from backend.features.captions.burn import _video_dimensions, burn_captions

# Font size as a fraction of frame height, and the readable box drawn behind the
# text so it stays legible over busy gameplay footage.
_FONT_SCALE = 0.045
_OUTLINE_PAD = 0.35  # box padding as a fraction of the font size (BorderStyle 3)
# Semi-transparent black box (ASS alpha: 00 opaque .. FF transparent).
_BOX_COLOUR = "&H64000000"
# Typewriter speed and the reveal-step budget that bounds the event count for
# long captions.
_CHARS_PER_SECOND = 28.0
_MAX_REVEAL_STEPS = 60
_MIN_REVEAL_SECONDS = 0.3

# Where a caption sits on the frame -> ASS numpad alignment.
_ALIGNMENT_BY_POSITION = {"top": 8, "middle": 5, "bottom": 2}
_DEFAULT_POSITION = "bottom"

_FONT_FAMILY = "Montserrat ExtraBold"

_HEADER_TEMPLATE = """\
[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Note,{font},{size},{primary},{primary},{box},{box},0,0,0,0,100,100,0,0,3,{pad},0,{alignment},{margin_h},{margin_h},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _reveal_seconds(text: str, span: float, override: float | None) -> float:
    """How long the typewriter takes to fully reveal ``text`` within ``span``."""
    if override is not None and override > 0:
        target = float(override)
    else:
        target = len(text) / _CHARS_PER_SECOND
    # Never exceed the caption's own on-screen span, and always leave the fully
    # revealed text visible for a beat.
    return max(_MIN_REVEAL_SECONDS, min(target, span * 0.85))


def _reveal_events(caption: dict, alignment: int) -> list[str]:
    """Build the Dialogue events that stream one caption onto the screen."""
    text = str(caption.get("text", "")).strip()
    if not text:
        return []
    start = float(caption["start"])
    end = float(caption["end"])
    if end <= start:
        return []

    display = _escape_text(text)
    total = len(display)
    reveal = _reveal_seconds(display, end - start, caption.get("reveal_seconds"))

    step_size = max(1, math.ceil(total / _MAX_REVEAL_STEPS))
    steps = math.ceil(total / step_size)
    dt = reveal / steps

    override = rf"{{\an{alignment}}}"
    events: list[str] = []
    for index in range(steps):
        revealed = min(total, (index + 1) * step_size)
        ev_start = start + index * dt
        # The last reveal step holds the full text until the caption ends.
        ev_end = end if index == steps - 1 else start + (index + 1) * dt
        ev_end = max(ev_end, ev_start + 0.01)
        events.append(
            f"Dialogue: 0,{_ass_time(ev_start)},{_ass_time(ev_end)},Note,,0,0,0,,"
            f"{override}{display[:revealed]}"
        )
    return events


def build_text_caption_ass(captions: list[dict], play_res: tuple[int, int]) -> str:
    """Build an ASS document that streams ``captions`` onto a video.

    Args:
        captions: Caption blocks, each ``{"start", "end", "text"}`` with an
            optional ``"position"`` (``top``/``middle``/``bottom``) and
            ``"reveal_seconds"``. Times are on the timeline of the video the
            document will be burned onto.
        play_res: ``(width, height)`` of the target video in display pixels.

    Returns:
        str: The ASS document text (write with UTF-8 encoding).
    """
    width, height = play_res
    font_size = round(height * _FONT_SCALE)
    # A per-document Style fixes the font/box/size; each caption overrides only
    # its alignment via an inline \an tag so mixed positions share one style.
    default_alignment = _ALIGNMENT_BY_POSITION[_DEFAULT_POSITION]
    header = _HEADER_TEMPLATE.format(
        width=width,
        height=height,
        font=_FONT_FAMILY,
        size=font_size,
        primary=_ass_colour("#FFFFFF"),
        box=_BOX_COLOUR,
        pad=round(font_size * _OUTLINE_PAD, 1),
        alignment=default_alignment,
        margin_h=round(width * 0.06),
        margin_v=round(height * 0.08),
    )

    events: list[str] = []
    for caption in captions:
        position = str(caption.get("position") or _DEFAULT_POSITION)
        alignment = _ALIGNMENT_BY_POSITION.get(position, default_alignment)
        events.extend(_reveal_events(caption, alignment))

    return header + "\n".join(events) + "\n"


def add_text_captions(
    video_path: str | Path,
    captions: list[dict],
    output_path: str | Path,
) -> None:
    """Burn streaming text captions into a video.

    Args:
        video_path: Video to caption; ``captions`` times must be on this
            video's timeline.
        captions: Caption blocks ``{"start", "end", "text", ...}`` (see
            :func:`build_text_caption_ass`).
        output_path: Where to write the captioned video.

    Raises:
        ValueError: If no caption has usable text.
        RuntimeError: If ffmpeg fails.
    """
    document = build_text_caption_ass(captions, _video_dimensions(video_path))
    if "Dialogue:" not in document:
        raise ValueError("No text captions to render")

    with tempfile.TemporaryDirectory() as tmp_dir:
        ass_path = Path(tmp_dir) / "text_captions.ass"
        ass_path.write_text(document, encoding="utf-8")
        burn_captions(video_path, ass_path, output_path)
