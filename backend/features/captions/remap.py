"""Remap source-timeline word timestamps onto a rendered output's timeline.

Word timestamps come from the transcript of the *source* video, but captions
are burned onto the *rendered* output — after cuts are removed and (when a
timeline is saved) segments are reordered. These helpers mirror the render
semantics of :mod:`backend.features.video_cutter.cut` exactly: the same spans
survive, in the same order, so a remapped word lands on screen precisely when
it is spoken in the output.
"""

from __future__ import annotations

from backend.features.video_cutter.cut import interval_minus_cuts


def output_intervals(
    duration: float,
    cut_ranges: list | None = None,
    segments: list | None = None,
) -> list[dict]:
    """Map the source spans that survive a render to output start times.

    Mirrors :func:`~backend.features.video_cutter.cut.render_with_edits` (no
    ``segments``) and :func:`~backend.features.video_cutter.cut.render_timeline`
    (ordered ``segments``, clamped to ``duration``, cuts subtracted from each).

    Args:
        duration: Duration of the source video in seconds.
        cut_ranges: Time ranges removed from the render, each ``{"start", "end"}``.
        segments: Ordered timeline segments ``{"start", "end"}`` when the
            project has a saved timeline; ``None`` renders the full source.

    Returns:
        list[dict]: Kept intervals in output order, each
        ``{"source_start", "source_end", "output_start"}``.
    """
    cuts = sorted(cut_ranges or [], key=lambda r: r["start"])
    if segments:
        source_spans = []
        for segment in segments:
            start = max(0.0, float(segment["start"]))
            end = min(duration, float(segment["end"]))
            if end > start:
                source_spans.append((start, end))
    else:
        source_spans = [(0.0, duration)]

    intervals: list[dict] = []
    cursor = 0.0
    for span_start, span_end in source_spans:
        for kept_start, kept_end in interval_minus_cuts(span_start, span_end, cuts):
            intervals.append(
                {
                    "source_start": kept_start,
                    "source_end": kept_end,
                    "output_start": cursor,
                }
            )
            cursor += kept_end - kept_start
    return intervals


def remap_words(words: list[dict], intervals: list[dict]) -> list[dict]:
    """Move words from the source timeline onto the output timeline.

    A word belongs to the first interval containing its midpoint (a segment
    that repeats a source range shows each word once); words whose midpoint
    was cut are dropped, and a word straddling an interval edge is clamped to
    the part that survived.

    Args:
        words: Word entries ``{"start", "end", "word"}`` in source time.
        intervals: Output intervals from :func:`output_intervals`.

    Returns:
        list[dict]: Remapped word entries sorted by output time.
    """
    remapped: list[dict] = []
    for word in words:
        start, end = float(word["start"]), float(word["end"])
        midpoint = (start + end) / 2.0
        for interval in intervals:
            if interval["source_start"] <= midpoint < interval["source_end"]:
                offset = interval["output_start"] - interval["source_start"]
                remapped.append(
                    {
                        "start": max(start, interval["source_start"]) + offset,
                        "end": min(end, interval["source_end"]) + offset,
                        "word": word["word"],
                    }
                )
                break
    remapped.sort(key=lambda w: w["start"])
    return remapped
