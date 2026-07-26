from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import proglog
from moviepy import (
    CompositeVideoClip,
    ImageClip,
    VideoFileClip,
    concatenate_videoclips,
)

from backend.features.face_detection.detect import detect_face_center

# Stock B-roll files with these extensions are still images, not videos.
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# A callback receiving render completion as a 0.0–1.0 fraction.
ProgressCallback = Callable[[float], None]


# The proglog bars MoviePy ticks once per written video frame ("frame_index" on
# MoviePy 2.x, "t" on 1.x). The audio pass uses a separate "chunk" bar which we
# deliberately ignore: it runs to completion first, so reporting it too would send
# progress back to zero when the video pass starts.
_VIDEO_PROGRESS_BARS = {"frame_index", "t"}


class _RenderProgressLogger(proglog.ProgressBarLogger):
    """proglog logger that forwards MoviePy's frame-write progress as a fraction.

    Translates the video bar's index/total into a 0.0-1.0 fraction and hands it to
    ``on_progress``, so the reported value climbs monotonically to completion.
    """

    def __init__(self, on_progress: ProgressCallback) -> None:
        super().__init__()
        self._on_progress = on_progress

    def bars_callback(self, bar, attr, value, old_value=None) -> None:  # noqa: D401
        if bar not in _VIDEO_PROGRESS_BARS or attr != "index":
            return
        total = self.bars[bar].get("total")
        if not total:
            return
        fraction = min(1.0, max(0.0, value / total))
        self._on_progress(fraction)


def _subclip(video: VideoFileClip, start: float, end: float):
    """Return a subclip across MoviePy 1.x and 2.x APIs."""
    if hasattr(video, "subclipped"):
        return video.subclipped(start, end)
    return video.subclip(start, end)


def _resize(clip, factor: float):
    """Scale a clip by ``factor`` across MoviePy 1.x and 2.x APIs."""
    if hasattr(clip, "resized"):
        return clip.resized(factor)
    return clip.resize(factor)


def _crop(clip, width: int, height: int, x_center: float, y_center: float):
    """Crop ``clip`` to ``width`` x ``height`` about a point (1.x/2.x)."""
    if hasattr(clip, "cropped"):
        return clip.cropped(
            width=width, height=height, x_center=x_center, y_center=y_center
        )
    return clip.crop(width=width, height=height, x_center=x_center, y_center=y_center)


def _without_audio(clip):
    """Strip a clip's audio track across MoviePy 1.x and 2.x APIs."""
    if hasattr(clip, "without_audio"):
        return clip.without_audio()
    return clip.set_audio(None)


def _with_audio(clip, audio):
    """Attach an audio track to a clip across MoviePy 1.x and 2.x APIs."""
    if hasattr(clip, "with_audio"):
        return clip.with_audio(audio)
    return clip.set_audio(audio)


def _with_position(clip, position):
    """Position a clip within a composite across MoviePy 1.x and 2.x APIs."""
    if hasattr(clip, "with_position"):
        return clip.with_position(position)
    return clip.set_position(position)


def _with_duration(clip, duration: float):
    """Set a clip's duration across MoviePy 1.x and 2.x APIs."""
    if hasattr(clip, "with_duration"):
        return clip.with_duration(duration)
    return clip.set_duration(duration)


def _apply_diagram_overlay(clip, overlay: VideoFileClip, offset: float):
    """Composite the slice of ``overlay`` starting at ``offset`` onto ``clip``.

    ``overlay`` is a full diagram animation timed to its edit range on the
    original video; ``offset`` is how far into that range ``clip`` starts, so
    cutting part of the range keeps the animation in sync with the remaining
    speech. The overlay is scaled to fit inside the frame (never cropped) and
    centered. If the offset falls past the end of the overlay (frame-rate
    rounding), the clip is returned unchanged.
    """
    if offset >= overlay.duration:
        return clip
    piece = _subclip(overlay, offset, min(offset + clip.duration, overlay.duration))
    scale = min(clip.w / piece.w, clip.h / piece.h)
    if scale != 1.0:
        piece = _resize(piece, scale)
    piece = _with_position(_without_audio(piece), "center")
    return CompositeVideoClip([clip, piece])


def _fit_frame(clip, width: int, height: int):
    """Scale ``clip`` to cover ``width`` x ``height`` and center-crop to it.

    Preserves the clip's aspect ratio (no stretching): it is scaled up until it
    covers the target frame, then cropped about its center back to exactly
    ``width`` x ``height``.
    """
    scale = max(width / clip.w, height / clip.h)
    scaled = _resize(clip, scale)
    return _crop(scaled, width, height, scaled.w / 2, scaled.h / 2)


def _stock_clip(footage_path: str, duration: float):
    """Load stock footage trimmed (or looped) to exactly ``duration`` seconds.

    The clip is silent — it is meant to overlay B-roll over speech, so the
    caller supplies the original audio. A still image (see IMAGE_EXTENSIONS)
    is held for the full span. When video footage is shorter than the
    requested span it is looped (fresh readers per copy to avoid sharing a
    single decoder); when longer it is trimmed from the start.
    """
    if Path(footage_path).suffix.lower() in IMAGE_EXTENSIONS:
        return _with_duration(ImageClip(footage_path), duration)

    clip = VideoFileClip(footage_path)
    if clip.duration >= duration:
        fitted = _subclip(clip, 0, duration)
    else:
        copies = [
            VideoFileClip(footage_path)
            for _ in range(int(duration // clip.duration) + 1)
        ]
        fitted = _subclip(concatenate_videoclips(copies), 0, duration)
    return _without_audio(fitted)


def _apply_stock_overlay(base_clip, footage_path: str):
    """Replace ``base_clip``'s video with stock footage, keeping its audio.

    The footage is fit to the base clip's frame size and duration, then the
    original audio (the speaker) is carried over so the result is a B-roll
    cutaway rather than a hard cut to silence.
    """
    stock = _stock_clip(footage_path, base_clip.duration)
    stock = _fit_frame(stock, base_clip.w, base_clip.h)
    return _with_audio(stock, base_clip.audio)


def _apply_zoom(clip, zoom_level: float, focus: tuple[float, float] | None = None):
    """Zoom into a clip about a focus point while preserving its frame size.

    The clip is scaled up by ``zoom_level`` and then cropped back to its original
    dimensions around ``focus``, producing a static "punch-in" effect. The crop
    window is clamped so it never falls outside the scaled frame.

    Args:
        clip: The MoviePy clip to zoom.
        zoom_level (float): Scale factor (e.g. 1.2 for a 20% zoom-in).
        focus (tuple[float, float] | None): ``(x, y)`` focus point in the clip's
            original pixel coordinates. Defaults to the frame center when ``None``.

    Returns:
        The zoomed clip, with the same width and height as the input.
    """
    width, height = clip.w, clip.h
    zoomed = _resize(clip, zoom_level)
    # Use the actual scaled dimensions (resize may round to whole pixels).
    ratio_x = zoomed.w / width
    ratio_y = zoomed.h / height

    if focus is None:
        x_center, y_center = zoomed.w / 2, zoomed.h / 2
    else:
        x_center = focus[0] * ratio_x
        y_center = focus[1] * ratio_y

    # Keep the crop window fully inside the scaled frame.
    x_center = min(max(x_center, width / 2), zoomed.w - width / 2)
    y_center = min(max(y_center, height / 2), zoomed.h - height / 2)
    return _crop(zoomed, width, height, x_center, y_center)


def _focus_for_span(video: VideoFileClip, start: float, end: float):
    """Return the face-center focus point for a zoom span, or ``None``.

    Samples a frame at the middle of the span and locates the largest face.
    Falls back to ``None`` (frame center) when no face is found or frame
    sampling/detection fails.
    """
    timestamp = min((start + end) / 2.0, max(0.0, video.duration - 1e-3))
    try:
        frame = video.get_frame(timestamp)
        return detect_face_center(frame)
    except Exception:
        return None


def interval_minus_cuts(
    start: float, end: float, cut_ranges: list
) -> list[tuple[float, float]]:
    """Return the sub-intervals of ``[start, end)`` kept after removing cuts."""
    intervals: list[tuple[float, float]] = []
    last_end = start
    for cut in sorted(cut_ranges, key=lambda r: r["start"]):
        cut_start = max(cut["start"], start)
        cut_end = min(cut["end"], end)
        if cut_end <= cut_start:
            continue
        if cut_start > last_end:
            intervals.append((last_end, cut_start))
        last_end = max(last_end, cut_end)

    if last_end < end:
        intervals.append((last_end, end))
    return intervals


def _kept_intervals(cut_ranges: list, duration: float) -> list[tuple[float, float]]:
    """Return the intervals of the source kept after removing ``cut_ranges``."""
    return interval_minus_cuts(0.0, duration, cut_ranges)


def _active_range(point: float, ranges: list) -> dict | None:
    """Return the first range in ``ranges`` covering ``point``, else ``None``."""
    for r in ranges:
        if r["start"] <= point < r["end"]:
            return r
    return None


def _segment_spans(
    start: float,
    end: float,
    zoom_ranges: list,
    stock_ranges: list,
    diagram_ranges: list | None = None,
) -> list[tuple[float, float, float | None, str | None, dict | None]]:
    """Split ``[start, end)`` into spans tagged with the effects covering them.

    Each returned tuple is ``(span_start, span_end, zoom_level, footage_path,
    diagram_range)``. The interval is cut at every zoom, stock-footage and
    diagram boundary that falls inside it, so each resulting span is uniformly
    covered (or not) by at most one range of each kind. ``zoom_level`` /
    ``footage_path`` / ``diagram_range`` are ``None`` outside their respective
    ranges. Effect selection per span is decided by the caller (stock footage
    takes precedence over zoom; diagrams composite on top of either).
    """
    diagrams = diagram_ranges or []
    boundaries = {start, end}
    for r in list(zoom_ranges) + list(stock_ranges) + list(diagrams):
        for edge in (r["start"], r["end"]):
            if start < edge < end:
                boundaries.add(edge)

    points = sorted(boundaries)
    spans: list[tuple[float, float, float | None, str | None, dict | None]] = []
    for span_start, span_end in zip(points, points[1:]):
        if span_end <= span_start:
            continue
        midpoint = (span_start + span_end) / 2.0
        zoom = _active_range(midpoint, zoom_ranges)
        stock = _active_range(midpoint, stock_ranges)
        level = zoom.get("level", 1.2) if zoom else None
        footage_path = stock.get("footage_path") if stock else None
        spans.append(
            (
                span_start,
                span_end,
                level,
                footage_path,
                _active_range(midpoint, diagrams),
            )
        )
    return spans


def render_with_edits(
    video_path: str,
    cut_ranges: list,
    zoom_ranges: list,
    output_path: str,
    stock_footage_ranges: list | None = None,
    diagram_ranges: list | None = None,
    on_progress: Optional[ProgressCallback] = None,
) -> None:
    """Render a video by removing cuts and applying zoom/B-roll/diagram effects.

    ``cut_ranges``, ``zoom_ranges``, ``stock_footage_ranges`` and
    ``diagram_ranges`` are all expressed on the *original* video timeline. Cut
    ranges are removed; the surviving segments are then split at every effect
    boundary so each sub-clip carries at most one effect of each kind, and the
    result is concatenated.

    Within a span, stock footage takes precedence over zoom: a B-roll cutaway
    replaces the speaker's video for the span while keeping the original audio,
    so zooming it would be meaningless. Diagram overlays composite on top of
    whichever base the span ends up with.

    Args:
        video_path (str): Path to the source video file.
        cut_ranges (list): Time ranges to remove, each ``{"start", "end"}``.
        zoom_ranges (list): Zoom ranges, each ``{"start", "end", "level"}`` where
            ``level`` is the zoom factor (defaults to 1.2 if missing).
        output_path (str): Path to write the rendered video to.
        stock_footage_ranges (list | None): B-roll overlays, each
            ``{"start", "end", "footage_path"}`` where ``footage_path`` points to
            a local stock-footage file to show over the span. Defaults to none.
        diagram_ranges (list | None): Animated diagram overlays, each
            ``{"start", "end", "overlay_path"}`` where ``overlay_path`` points
            to a rendered alpha-channel diagram video timed to the range.
        on_progress (ProgressCallback | None): Called with the frame-write
            progress as a 0.0–1.0 fraction while the output is encoded.
    """
    video = VideoFileClip(video_path)
    sorted_zooms = sorted(zoom_ranges, key=lambda r: r["start"])
    sorted_stock = sorted(stock_footage_ranges or [], key=lambda r: r["start"])
    sorted_diagrams = sorted(diagram_ranges or [], key=lambda r: r["start"])
    overlays = _load_diagram_overlays(sorted_diagrams)

    clips_to_keep = []
    for interval_start, interval_end in _kept_intervals(cut_ranges, video.duration):
        clips_to_keep.extend(
            _effect_clips(
                video,
                interval_start,
                interval_end,
                sorted_zooms,
                sorted_stock,
                sorted_diagrams,
                overlays,
            )
        )

    _write_concatenated(video, clips_to_keep, output_path, on_progress)


def _load_diagram_overlays(diagram_ranges: list) -> dict:
    """Open each diagram overlay video once, keyed by path.

    Transparent overlays are ``.mov`` files with an alpha channel; diagrams
    rendered on a solid background are opaque ``.mp4`` files.
    """
    overlays: dict[str, VideoFileClip] = {}
    for r in diagram_ranges:
        path = r.get("overlay_path")
        if path and path not in overlays:
            overlays[path] = VideoFileClip(path, has_mask=path.endswith(".mov"))
    return overlays


def _effect_clips(
    video: VideoFileClip,
    interval_start: float,
    interval_end: float,
    zoom_ranges: list,
    stock_ranges: list,
    diagram_ranges: list | None = None,
    diagram_overlays: dict | None = None,
) -> list:
    """Build the effect-applied subclips covering one kept interval."""
    clips = []
    for span_start, span_end, level, footage_path, diagram in _segment_spans(
        interval_start, interval_end, zoom_ranges, stock_ranges, diagram_ranges
    ):
        clip = _subclip(video, span_start, span_end)
        if footage_path:
            clip = _apply_stock_overlay(clip, footage_path)
        elif level and level != 1.0:
            focus = _focus_for_span(video, span_start, span_end)
            clip = _apply_zoom(clip, level, focus)
        if diagram:
            overlay = (diagram_overlays or {}).get(diagram.get("overlay_path"))
            if overlay is not None:
                clip = _apply_diagram_overlay(
                    clip, overlay, span_start - diagram["start"]
                )
        clips.append(clip)
    return clips


def _write_concatenated(
    video: VideoFileClip,
    clips: list,
    output_path: str,
    on_progress: Optional[ProgressCallback] = None,
) -> None:
    """Concatenate ``clips`` and write the result (empty video when none).

    When ``on_progress`` is given, frame-write progress is reported through it as
    a 0.0–1.0 fraction; otherwise MoviePy's default console bar is used.
    """
    logger = _RenderProgressLogger(on_progress) if on_progress else "bar"
    if clips:
        final_clip = concatenate_videoclips(clips)
        # Still-image overlays have no fps of their own; fall back to the source's.
        fps = getattr(final_clip, "fps", None) or video.fps
        final_clip.write_videofile(
            output_path, fps=fps, codec="libx264", audio_codec="aac", logger=logger
        )
    else:
        # If everything was cut, write an empty video.
        _subclip(video, 0, 0).write_videofile(
            output_path, codec="libx264", audio_codec="aac", logger=logger
        )


def render_timeline(
    video_path: str,
    segments: list,
    output_path: str,
    cut_ranges: list | None = None,
    zoom_ranges: list | None = None,
    stock_footage_ranges: list | None = None,
    diagram_ranges: list | None = None,
    on_progress: Optional[ProgressCallback] = None,
) -> None:
    """Render ordered timeline segments, composing source-time edits.

    ``segments`` is an *ordered* list of ``{"start", "end"}`` source ranges; the
    output plays them in list order, which may differ from source order (segments
    can be rearranged, and gaps between them are omitted). Cut ranges are
    subtracted from every segment they intersect, and zoom / stock-footage /
    diagram effects are applied to the spans they cover — all expressed on the
    original video's timeline, with the same semantics as
    :func:`render_with_edits`.

    Args:
        video_path (str): Path to the source video file.
        segments (list): Ordered source ranges to play, each ``{"start", "end"}``.
        output_path (str): Path to write the rendered video to.
        cut_ranges (list | None): Time ranges to remove, each ``{"start", "end"}``.
        zoom_ranges (list | None): Zoom ranges, each ``{"start", "end", "level"}``.
        stock_footage_ranges (list | None): B-roll overlays, each
            ``{"start", "end", "footage_path"}``.
        diagram_ranges (list | None): Animated diagram overlays, each
            ``{"start", "end", "overlay_path"}``.
        on_progress (ProgressCallback | None): Called with the frame-write
            progress as a 0.0–1.0 fraction while the output is encoded.
    """
    video = VideoFileClip(video_path)
    duration = float(video.duration)
    cuts = sorted(cut_ranges or [], key=lambda r: r["start"])
    zooms = sorted(zoom_ranges or [], key=lambda r: r["start"])
    stock = sorted(stock_footage_ranges or [], key=lambda r: r["start"])
    diagrams = sorted(diagram_ranges or [], key=lambda r: r["start"])
    overlays = _load_diagram_overlays(diagrams)

    clips = []
    for segment in segments:
        segment_start = max(0.0, float(segment["start"]))
        segment_end = min(duration, float(segment["end"]))
        if segment_end <= segment_start:
            continue
        for interval_start, interval_end in interval_minus_cuts(
            segment_start, segment_end, cuts
        ):
            clips.extend(
                _effect_clips(
                    video,
                    interval_start,
                    interval_end,
                    zooms,
                    stock,
                    diagrams,
                    overlays,
                )
            )

    _write_concatenated(video, clips, output_path, on_progress)


def cut_filler_words(
    video_path: str, filler_word_ranges: list, output_path: str
) -> None:
    """
    Cuts filler words from a video file.

    Args:
        video_path (str): The path to the video file.
        filler_word_ranges (list): A list of time ranges for the filler words.
                                   Each time range is a dictionary with "start" and "end" keys.
        output_path (str): The path to save the edited video file.
    """
    render_with_edits(video_path, filler_word_ranges, [], output_path)
