"""Caption style presets for shorts-style burned-in captions.

Each preset describes the full look of a caption track — font, colours,
outline, position and the active-word treatment (highlight colour and/or a
scale "pop"). Sizes are expressed as fractions of the video frame so the same
preset works for landscape and portrait renders alike.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Bundled OFL-licensed fonts (see backend/assets/fonts/README.md). Passed to
# libass via the ffmpeg ``fontsdir`` option so output never depends on the
# host's installed fonts.
FONTS_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"

# Font family name (as libass matches it) -> bundled file.
FONT_FILES = {
    "Anton": "Anton-Regular.ttf",
    "Bangers": "Bangers-Regular.ttf",
    "Montserrat ExtraBold": "Montserrat-ExtraBold.ttf",
}


# Preset used when a captions edit doesn't name one.
DEFAULT_STYLE = "bold-pop"


@dataclass(frozen=True)
class CaptionStyle:
    """The visual definition of one caption preset.

    Attributes:
        name: Preset identifier (kebab-case, used by the API).
        font_family: Font family name; must match a key of ``FONT_FILES`` (or
            an installed system font).
        font_scale: Font size as a fraction of the video frame height.
        text_colour: ``#RRGGBB`` colour of non-active words.
        highlight_colour: ``#RRGGBB`` colour of the word being spoken, or
            ``None`` to keep the active word in ``text_colour``.
        outline_colour: ``#RRGGBB`` colour of the text outline.
        outline_scale: Outline thickness as a fraction of the font size.
        shadow_scale: Drop-shadow depth as a fraction of the font size.
        alignment: ASS numpad alignment (2 = bottom-center, 5 = middle-center).
        margin_v_scale: Vertical margin as a fraction of the frame height
            (distance from the bottom edge for bottom alignments).
        uppercase: Whether to render all caption text in capitals.
        pop_scale: Peak percentage the active word scales to before settling
            back to 100 (e.g. 118), or ``None`` for no pop animation.
        word_colours: When non-empty, words cycle through these colours in
            order ("rainbow" captions); overrides ``text_colour`` per word.
        max_words_per_line: Default words per caption page for this preset.
    """

    name: str
    font_family: str
    font_scale: float = 0.06
    text_colour: str = "#FFFFFF"
    highlight_colour: str | None = None
    outline_colour: str = "#000000"
    outline_scale: float = 0.05
    shadow_scale: float = 0.0
    alignment: int = 2
    margin_v_scale: float = 0.24
    uppercase: bool = True
    pop_scale: int | None = None
    word_colours: tuple[str, ...] = ()
    max_words_per_line: int = 3

    @property
    def has_word_highlight(self) -> bool:
        """Whether the active word is styled differently from the rest.

        Highlighted styles need one ASS event per word; plain styles render
        one event per caption page.
        """
        return bool(self.highlight_colour or self.pop_scale or self.word_colours)


STYLE_PRESETS: dict[str, CaptionStyle] = {
    style.name: style
    for style in (
        # White text, spoken word flips yellow and pops — the classic
        # talking-head shorts look.
        CaptionStyle(
            name="bold-pop",
            font_family="Montserrat ExtraBold",
            font_scale=0.062,
            highlight_colour="#FFD900",
            outline_scale=0.06,
            pop_scale=118,
        ),
        # Loud comic-style font with each word in a different colour.
        CaptionStyle(
            name="rainbow",
            font_family="Bangers",
            font_scale=0.075,
            word_colours=("#FF4D4D", "#FFD900", "#4DFF88", "#4DC9FF", "#D98CFF"),
            outline_scale=0.055,
            shadow_scale=0.04,
            pop_scale=122,
        ),
        # Whole phrase on screen, spoken word highlighted green.
        CaptionStyle(
            name="karaoke",
            font_family="Anton",
            font_scale=0.058,
            highlight_colour="#00E86C",
            outline_scale=0.05,
            max_words_per_line=4,
        ),
        # Clean lower-key captions: mixed case, soft shadow, no highlight.
        CaptionStyle(
            name="minimal",
            font_family="Montserrat ExtraBold",
            font_scale=0.045,
            uppercase=False,
            outline_scale=0.0,
            shadow_scale=0.08,
            margin_v_scale=0.12,
            max_words_per_line=5,
        ),
    )
}


def get_style(name: str) -> CaptionStyle:
    """Return the preset named ``name``.

    Args:
        name: A key of ``STYLE_PRESETS``.

    Returns:
        CaptionStyle: The matching preset.

    Raises:
        ValueError: If no preset with that name exists.
    """
    style = STYLE_PRESETS.get(name)
    if style is None:
        raise ValueError(
            f"Unknown caption style '{name}'. "
            f"Available styles: {', '.join(sorted(STYLE_PRESETS))}"
        )
    return style
