"""Group word-level transcript entries into caption pages.

A "page" is the short run of words shown on screen together (shorts-style
captions show 2-5 words at a time). Pages break on a word budget, on sentence
punctuation, and on speech gaps, and each page lingers briefly (or until the
next page starts) so captions don't flicker between words.
"""

from __future__ import annotations

DEFAULT_MAX_WORDS = 3
# A silence longer than this between words starts a new page.
DEFAULT_MAX_GAP = 1.0
# How long a page may stay on screen after its last word ends.
DEFAULT_LINGER = 0.5

_SENTENCE_END = (".", "!", "?")


def group_words(
    words: list[dict],
    max_words: int = DEFAULT_MAX_WORDS,
    max_gap: float = DEFAULT_MAX_GAP,
    linger: float = DEFAULT_LINGER,
) -> list[dict]:
    """Split a word-level transcript into caption pages.

    Args:
        words: Word entries, each ``{"start", "end", "word"}``, in time order
            (the shape produced by the transcript feature).
        max_words: Maximum words shown on screen at once.
        max_gap: Speech gap (seconds) that forces a new page.
        linger: Seconds a page holds after its last word; a page also extends
            to meet the next page when the gap between them is within this,
            so captions never flicker off and straight back on.

    Returns:
        list[dict]: Pages ``{"start", "end", "words"}`` where ``words`` is the
        page's cleaned word entries. Words with empty text are dropped.
    """
    groups: list[list[dict]] = []
    current: list[dict] = []
    for raw in words:
        text = str(raw["word"]).strip()
        if not text:
            continue
        word = {"start": float(raw["start"]), "end": float(raw["end"]), "word": text}
        if current:
            gap_break = word["start"] - current[-1]["end"] > max_gap
            sentence_break = current[-1]["word"].endswith(_SENTENCE_END)
            if len(current) >= max_words or gap_break or sentence_break:
                groups.append(current)
                current = []
        current.append(word)
    if current:
        groups.append(current)

    pages: list[dict] = []
    for index, page_words in enumerate(groups):
        end = page_words[-1]["end"]
        if index + 1 < len(groups):
            next_start = groups[index + 1][0]["start"]
            end = next_start if next_start - end <= linger else end + linger
        else:
            end += linger
        pages.append({"start": page_words[0]["start"], "end": end, "words": page_words})
    return pages
