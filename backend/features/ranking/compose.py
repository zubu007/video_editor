"""Shared layout, overlay rasterisation and layout validation.

Preview and export both use :func:`render_overlay`, so wrapping, outline and positions
are identical by construction. Overlays are transparent 1080x1920 RGBA images drawn over
the footage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from backend.features.ranking.schema import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    MAX_HEADING_LINES,
    RankingDocument,
)

FONT_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"
FONT_FILES = {
    "montserrat": "Montserrat-ExtraBold.ttf",
    "anton": "Anton-Regular.ttf",
    "bangers": "Bangers-Regular.ttf",
}
HEADING_MARGIN = 48
HEADER_BAND_HEIGHT = 220
MIN_TITLE_SIZE = 32
MIN_NUMBER_SIZE = 48
LINE_SPACING = 1.15
TITLE_GAP = 16


@dataclass
class Issue:
    """A problem that blocks export, tied to a field."""

    field: str
    message: str

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-friendly dict."""
        return {"field": self.field, "message": self.message}


@lru_cache(maxsize=64)
def load_font(key: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a bundled font at ``size``."""
    return ImageFont.truetype(str(FONT_DIR / FONT_FILES[key]), size)


def _glyph_bytes(font: ImageFont.FreeTypeFont, char: str) -> bytes:
    canvas = Image.new("L", (120, 120), 0)
    ImageDraw.Draw(canvas).text((10, 10), char, font=font, fill=255)
    return canvas.tobytes()


@lru_cache(maxsize=8)
def _notdef_mask(key: str) -> bytes:
    return _glyph_bytes(load_font(key, 64), "\uffff")


def unsupported_chars(text: str, font_key: str) -> list[str]:
    """Return characters in ``text`` the bundled font cannot render."""
    font = load_font(font_key, 64)
    notdef = _notdef_mask(font_key)
    missing: list[str] = []
    for char in dict.fromkeys(text):
        if char.isspace() or char == "\n":
            continue
        if _glyph_bytes(font, char) == notdef:
            missing.append(char)
    return missing


def _hex(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    return (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16), alpha)


def _line_height(size: int) -> int:
    return int(size * LINE_SPACING)


Glyphs = list[tuple[str, str | None]]  # (char, accent colour)


def _wrap(
    glyphs: Glyphs, font: ImageFont.FreeTypeFont, max_width: float
) -> tuple[list[Glyphs], bool]:
    """Greedy word wrap that preserves explicit newlines.

    Returns the lines and whether any single word was wider than ``max_width``.
    """
    lines: list[Glyphs] = []
    too_wide = False
    paragraphs: list[Glyphs] = [[]]
    for char, color in glyphs:
        if char == "\n":
            paragraphs.append([])
        else:
            paragraphs[-1].append((char, color))

    for paragraph in paragraphs:
        words: list[Glyphs] = [[]]
        for item in paragraph:
            if item[0] == " ":
                words.append([])
            else:
                words[-1].append(item)
        current: Glyphs = []
        for word in words:
            if not word:
                continue
            word_text = "".join(c for c, _ in word)
            if font.getlength(word_text) > max_width:
                too_wide = True
            candidate = current + ([(" ", None)] if current else []) + word
            if current and font.getlength("".join(c for c, _ in candidate)) > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)
    return lines, too_wide


@dataclass
class HeadingLayout:
    """Wrapped heading text and its vertical block."""

    lines: list[Glyphs]
    top: int
    line_height: int
    overflow: list[str] = field(default_factory=list)


@dataclass
class RowLayout:
    """One ranking row, by rank."""

    rank: int
    clip_id: str
    row_top: float
    row_height: float
    number_size: int
    title_size: int
    title_lines: list[str]
    overflow: bool


@dataclass
class Layout:
    """Everything needed to draw and validate a composition."""

    heading: HeadingLayout
    rows: list[RowLayout]


def _heading_layout(doc: RankingDocument) -> HeadingLayout:
    heading = doc.heading
    glyphs: Glyphs = [(char, run.color) for run in heading.runs for char in run.text]
    font = load_font(heading.font, heading.size)
    lines, too_wide = _wrap(
        glyphs, font, CANVAS_WIDTH - 2 * HEADING_MARGIN - 2 * heading.outline_width
    )
    line_height = _line_height(heading.size)
    block = line_height * len(lines)
    top = max(0, int(heading.y - block / 2))
    overflow: list[str] = []
    if too_wide:
        overflow.append("A heading word is wider than the frame.")
    if len(lines) > MAX_HEADING_LINES:
        overflow.append(
            f"Heading wraps to {len(lines)} lines; the maximum is {MAX_HEADING_LINES}."
        )
    if doc.canvas.preset == "header_band" and block > HEADER_BAND_HEIGHT - 20:
        overflow.append("Heading does not fit inside the header band.")
    if top + block > CANVAS_HEIGHT:
        overflow.append("Heading runs off the bottom of the frame.")
    return HeadingLayout(lines, top, line_height, overflow)


def _fit_title(
    name: str, style_font: str, start_size: int, width: int, row_height: float
) -> tuple[int, list[str], bool]:
    """Shrink a title from ``start_size`` to the minimum until it fits."""
    if not name.strip():
        return start_size, [], False
    size = start_size
    while True:
        font = load_font(style_font, size)
        glyphs: Glyphs = [(c, None) for c in name]
        wrapped, too_wide = _wrap(glyphs, font, width)
        lines = ["".join(c for c, _ in line) for line in wrapped]
        fits = (
            not too_wide
            and len(lines) <= 2
            and len(lines) * _line_height(size) <= row_height
        )
        if fits:
            return size, lines, False
        if size <= MIN_TITLE_SIZE:
            return size, lines, True
        size = max(MIN_TITLE_SIZE, size - 2)


def compute_layout(doc: RankingDocument) -> Layout:
    """Compute heading and ranking-row geometry for ``doc``."""
    style = doc.ranking
    count = len(doc.clips)
    row_height = (style.bottom - style.top) / count
    inner_width = style.title_width - 2 * style.outline_width
    rows: list[RowLayout] = []
    for clip in sorted(doc.clips, key=lambda c: c.rank):
        number_size = max(
            MIN_NUMBER_SIZE, min(style.number_size, int(row_height * 0.8))
        )
        title_size, lines, overflow = _fit_title(
            clip.name, style.font, style.title_size, inner_width, row_height
        )
        rows.append(
            RowLayout(
                rank=clip.rank,
                clip_id=clip.id,
                row_top=style.top + (clip.rank - 1) * row_height,
                row_height=row_height,
                number_size=number_size,
                title_size=title_size,
                title_lines=lines,
                overflow=overflow,
            )
        )
    return Layout(_heading_layout(doc), rows)


def layout_issues(doc: RankingDocument) -> list[Issue]:
    """Return text overflow / glyph issues that must block export."""
    layout = compute_layout(doc)
    issues = [Issue("heading", message) for message in layout.heading.overflow]
    heading_missing = unsupported_chars(doc.heading.text, doc.heading.font)
    if heading_missing:
        issues.append(
            Issue(
                "heading",
                "Heading uses characters the font cannot draw: "
                + " ".join(heading_missing),
            )
        )
    names = {clip.id: clip for clip in doc.clips}
    for row in layout.rows:
        clip = names[row.clip_id]
        label = f"clip:{clip.id}"
        if row.overflow:
            issues.append(
                Issue(
                    label,
                    f"Name for rank {row.rank} is too long; shorten it or widen "
                    "the title column.",
                )
            )
        missing = unsupported_chars(clip.name, doc.ranking.font)
        if missing:
            issues.append(
                Issue(
                    label,
                    f"Name for rank {row.rank} uses characters the font cannot "
                    "draw: " + " ".join(missing),
                )
            )
    return issues


def _draw_text(
    image: Image.Image,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
    outline: str,
    outline_width: int,
    shadow: bool,
) -> None:
    """Draw outlined text with its baseline-top at ``xy`` (anchor ``la``)."""
    if shadow:
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).text(
            (xy[0] + 4, xy[1] + 5),
            text,
            font=font,
            fill=(0, 0, 0, 170),
            stroke_width=outline_width,
            stroke_fill=(0, 0, 0, 170),
        )
        image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(3)))
    ImageDraw.Draw(image).text(
        xy,
        text,
        font=font,
        fill=_hex(fill),
        stroke_width=outline_width,
        stroke_fill=_hex(outline),
    )


def _draw_heading(image: Image.Image, doc: RankingDocument, layout: Layout) -> None:
    heading = doc.heading
    font = load_font(heading.font, heading.size)
    hl = layout.heading
    if heading.backing_opacity > 0:
        backing = Image.new("RGBA", image.size, (0, 0, 0, 0))
        ImageDraw.Draw(backing).rectangle(
            (
                0,
                max(0, hl.top - 20),
                CANVAS_WIDTH,
                hl.top + hl.line_height * len(hl.lines) + 20,
            ),
            fill=_hex(heading.backing_color, round(255 * heading.backing_opacity)),
        )
        image.alpha_composite(backing)

    for line_index, line in enumerate(hl.lines):
        text = "".join(c for c, _ in line)
        width = font.getlength(text)
        area = CANVAS_WIDTH - 2 * HEADING_MARGIN
        if heading.align == "center":
            x = HEADING_MARGIN + (area - width) / 2
        elif heading.align == "right":
            x = HEADING_MARGIN + area - width
        else:
            x = HEADING_MARGIN
        y = hl.top + line_index * hl.line_height
        # Draw runs of equal colour left to right; width advances by measured text.
        start = 0
        while start < len(line):
            end = start
            while end < len(line) and line[end][1] == line[start][1]:
                end += 1
            piece = "".join(c for c, _ in line[start:end])
            _draw_text(
                image,
                (x, y),
                piece,
                font,
                line[start][1] or heading.fill,
                heading.outline_color,
                heading.outline_width,
                heading.shadow,
            )
            x += font.getlength(piece)
            start = end


def _draw_rows(
    image: Image.Image,
    doc: RankingDocument,
    layout: Layout,
    revealed: set[str],
    active_clip_id: str | None,
) -> None:
    style = doc.ranking
    for row in layout.rows:
        number_font = load_font(style.font, row.number_size)
        text = str(row.rank)
        width = number_font.getlength(text)
        number_color = style.number_colors.get(str(row.rank), style.number_color)
        if row.clip_id == active_clip_id:
            number_color = style.active_color
        centre_y = row.row_top + row.row_height / 2
        ascent, descent = number_font.getmetrics()
        _draw_text(
            image,
            (
                style.left + (style.number_width - width) / 2,
                centre_y - (ascent + descent) / 2,
            ),
            text,
            number_font,
            number_color,
            style.outline_color,
            style.outline_width,
            style.shadow,
        )

        if row.clip_id not in revealed or not row.title_lines:
            continue
        title_font = load_font(style.font, row.title_size)
        line_h = _line_height(row.title_size)
        block_top = centre_y - line_h * len(row.title_lines) / 2
        box_left = style.left + style.number_width + TITLE_GAP
        for i, line in enumerate(row.title_lines):
            line_width = title_font.getlength(line)
            if style.title_align == "center":
                x = box_left + (style.title_width - line_width) / 2
            elif style.title_align == "right":
                x = box_left + style.title_width - line_width
            else:
                x = box_left
            _draw_text(
                image,
                (x, block_top + i * line_h),
                line,
                title_font,
                style.title_color,
                style.outline_color,
                style.outline_width,
                style.shadow,
            )


def render_overlay(
    doc: RankingDocument,
    revealed_clip_ids: list[str],
    active_clip_id: str | None,
) -> Image.Image:
    """Rasterise the heading and ranking column for one reveal state."""
    image = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 0))
    layout = compute_layout(doc)
    _draw_heading(image, doc, layout)
    _draw_rows(image, doc, layout, set(revealed_clip_ids), active_clip_id)
    return image
