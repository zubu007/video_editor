"""Build ASS (Advanced SubStation Alpha) documents from caption pages.

ASS is rendered by libass via ffmpeg's ``ass`` filter and natively supports
everything the shorts-caption look needs: per-word timing, colours, thick
outlines, custom fonts and scale animations. For styles that highlight the
spoken word, each page becomes one Dialogue event *per word* — every event
shows the whole page with a different word emphasised — which is the standard
technique for word-by-word caption highlighting.
"""

from __future__ import annotations

from backend.features.captions.styles import CaptionStyle

# Active-word pop timing (milliseconds from event start): grow, then settle.
_POP_UP_MS = 70
_POP_SETTLE_MS = 140

_HEADER_TEMPLATE = """\
[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font},{size},{primary},{primary},{outline_colour},{outline_colour},0,0,0,0,100,100,0,0,1,{outline},{shadow},{alignment},{margin_h},{margin_h},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_colour(hex_colour: str) -> str:
    """Convert ``#RRGGBB`` to the ASS ``&HAABBGGRR`` colour form (opaque)."""
    value = hex_colour.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Expected a #RRGGBB colour, got '{hex_colour}'")
    red, green, blue = value[0:2], value[2:4], value[4:6]
    return f"&H00{blue}{green}{red}".upper()


def _ass_time(seconds: float) -> str:
    """Format ``seconds`` as an ASS timestamp (``H:MM:SS.CC``)."""
    total_cs = max(0, round(seconds * 100))
    hours, remainder = divmod(total_cs, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    secs, centis = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _escape_text(text: str) -> str:
    """Neutralise characters ASS treats specially inside event text."""
    return (
        text.replace("{", "(").replace("}", ")").replace("\n", " ").replace("\\", "/")
    )


def _word_part(word: str, style: CaptionStyle, colour: str | None, active: bool) -> str:
    """Render one word of a page, with override tags for colour and pop."""
    tags = ""
    if colour and colour != style.text_colour:
        tags += rf"\c{_ass_colour(colour)}"
    if active and style.pop_scale:
        pop = style.pop_scale
        tags += (
            rf"\t(0,{_POP_UP_MS},\fscx{pop}\fscy{pop})"
            rf"\t({_POP_UP_MS},{_POP_SETTLE_MS},\fscx100\fscy100)"
        )
    text = _escape_text(word.upper() if style.uppercase else word)
    part = f"{{{tags}}}{text}" if tags else text
    # \r resets colour/scale so the animation doesn't bleed into later words.
    return f"{part}{{\\r}}" if tags else part


def _page_text(
    page_words: list[dict], style: CaptionStyle, active_index: int | None
) -> str:
    """Build the event text for a page with ``active_index`` emphasised."""
    parts = []
    for index, word in enumerate(page_words):
        colour = None
        if style.word_colours:
            colour = style.word_colours[index % len(style.word_colours)]
        if index == active_index and style.highlight_colour:
            colour = style.highlight_colour
        parts.append(_word_part(word["word"], style, colour, index == active_index))
    return " ".join(parts)


def build_ass(pages: list[dict], style: CaptionStyle, play_res: tuple[int, int]) -> str:
    """Build a complete ASS document for ``pages`` in ``style``.

    Args:
        pages: Caption pages from :func:`~backend.features.captions.layout.group_words`.
        style: The caption preset to render with.
        play_res: ``(width, height)`` of the target video in display pixels;
            the script's coordinate space, so fractional sizes in ``style``
            resolve against the real frame.

    Returns:
        str: The ASS document text (write with UTF-8 encoding).
    """
    width, height = play_res
    font_size = round(height * style.font_scale)
    header = _HEADER_TEMPLATE.format(
        width=width,
        height=height,
        font=style.font_family,
        size=font_size,
        primary=_ass_colour(style.text_colour),
        outline_colour=_ass_colour(style.outline_colour),
        outline=round(font_size * style.outline_scale, 1),
        shadow=round(font_size * style.shadow_scale, 1),
        alignment=style.alignment,
        margin_h=round(width * 0.05),
        margin_v=round(height * style.margin_v_scale),
    )

    events = []
    for page in pages:
        page_words = page["words"]
        if style.has_word_highlight:
            # One event per word: same text, different word emphasised.
            for index, word in enumerate(page_words):
                start = word["start"]
                if index + 1 < len(page_words):
                    end = page_words[index + 1]["start"]
                else:
                    end = page["end"]
                end = max(end, start + 0.01)
                events.append(
                    f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caption,,0,0,0,,"
                    f"{_page_text(page_words, style, index)}"
                )
        else:
            events.append(
                f"Dialogue: 0,{_ass_time(page['start'])},{_ass_time(page['end'])},Caption,,0,0,0,,"
                f"{_page_text(page_words, style, None)}"
            )

    return header + "\n".join(events) + "\n"
