"""Shorts-style animated captions burned into videos via ASS + ffmpeg/libass."""

from backend.features.captions.ass_builder import build_ass
from backend.features.captions.burn import add_captions, burn_captions, video_duration
from backend.features.captions.layout import group_words
from backend.features.captions.remap import output_intervals, remap_words
from backend.features.captions.styles import (
    DEFAULT_STYLE,
    FONTS_DIR,
    STYLE_PRESETS,
    CaptionStyle,
    get_style,
)
from backend.features.captions.text_caption import (
    add_text_captions,
    build_text_caption_ass,
)

__all__ = [
    "DEFAULT_STYLE",
    "FONTS_DIR",
    "STYLE_PRESETS",
    "CaptionStyle",
    "add_captions",
    "add_text_captions",
    "build_ass",
    "build_text_caption_ass",
    "burn_captions",
    "get_style",
    "group_words",
    "output_intervals",
    "remap_words",
    "video_duration",
]
