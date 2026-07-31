"""Reframe a landscape gameplay clip as a square reel, keeping the HUD that matters.

Reels are posted at 1:1 or taller, so a 16:9 recording has to give up ~44% of its
width. Cropping equally from both sides keeps the action centred and — on the
standard Dota HUD — preserves the top hero bar and the bottom hero/ability/item
panel almost exactly. What it throws away are the two readouts a viewer needs to
follow a highlight: the minimap in the bottom-left corner and the K/D/A counter
in the top-left. This module lifts those two regions out of the discarded bands
and composites them back onto the square frame, enlarged so they stay legible on
a phone.

The whole reframe is expressed as a single ffmpeg ``-filter_complex`` graph
(:func:`build_reel_filter`), so the highlight job stays one re-encode pass rather
than a crop pass plus an overlay pass.

Geometry in :class:`ReelLayout` is calibrated against a 1920x1080 recording with
the standard HUD and scales proportionally, the same convention
:class:`~backend.features.gaming.death_detect.DotaHudLayout` uses. A different
in-game HUD scale shifts the source boxes and will silently produce a wrong crop
rather than fail.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# ffmpeg stream labels for the reframe graph. Prefixed so the graph can be
# concatenated with other filters without colliding on label names.
REEL_OUTPUT_LABEL = "reel_out"


def video_dimensions(video_path: str | Path) -> tuple[int, int]:
    """Return the ``(width, height)`` of a video in pixels."""
    from moviepy import VideoFileClip

    clip = VideoFileClip(str(video_path))
    try:
        return int(clip.w), int(clip.h)
    finally:
        clip.close()


@dataclass(frozen=True)
class ReelLayout:
    """Where the rescued HUD elements live in the source and in the square frame.

    Source boxes are ``(x0, y0, x1, y1)`` in the calibrated recording's pixels.
    Placement values (``*_x``, ``*_y``, ``minimap_bottom``) are in the *output*
    square's pixels at the calibrated size, where the square's side equals
    :attr:`height`. Both sets scale proportionally for other resolutions.
    """

    width: int = 1920
    height: int = 1080
    # The whole minimap widget including its stone frame, so it still reads as a
    # HUD element rather than a floating square of map.
    minimap_box: tuple[int, int, int, int] = (0, 783, 288, 1080)
    # Both readout rows: `K/D/A a/b/c` and `LH/DN d/e`. Wide enough for three
    # double-digit numbers.
    kda_box: tuple[int, int, int, int] = (0, 56, 170, 102)
    minimap_scale: float = 1.3
    kda_scale: float = 2.0
    minimap_x: int = 10
    # The minimap's *bottom* edge is pinned rather than its top: it stops just
    # above the ability bar, so growing it never covers the hero portrait.
    minimap_bottom: int = 898
    kda_x: int = 18
    # Clears the top hero bar, which ends at y=40 on the calibrated HUD.
    kda_y: int = 52


@dataclass(frozen=True)
class ReelPlacement:
    """Concrete pixel geometry of the reframe for one source resolution.

    All rectangles are ``(x, y, width, height)``. ``*_src`` are crops from the
    source frame; ``*_dst`` are where those crops land in the square output.
    """

    side: int
    crop_x: int
    minimap_src: tuple[int, int, int, int]
    minimap_dst: tuple[int, int, int, int]
    kda_src: tuple[int, int, int, int]
    kda_dst: tuple[int, int, int, int]


def _even(value: int) -> int:
    """Round down to an even number (libx264 rejects odd output dimensions)."""
    return value - (value % 2)


def plan_reel(
    width: int, height: int, layout: ReelLayout | None = None
) -> ReelPlacement:
    """Work out the square crop and the two HUD overlays for a source size.

    Args:
        width: Source video width in pixels.
        height: Source video height in pixels.
        layout: HUD geometry; defaults to the calibrated layout.

    Returns:
        ReelPlacement: The crop window and both overlay rectangles, clamped so
        every overlay lies inside the square.

    Raises:
        ValueError: If the source is not landscape — there is nothing to crop
            from the sides, and the HUD regions would be part of the kept frame.
    """
    layout = layout or ReelLayout()
    if width <= height:
        raise ValueError(
            f"Source is {width}x{height}; the square reframe needs a landscape video."
        )

    side = _even(height)
    crop_x = _even((width - side) // 2)
    # Source boxes scale with the recording's resolution; placements scale with
    # the output square, whose side is the calibrated height.
    sx, sy = width / layout.width, height / layout.height
    k = side / layout.height

    def src(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        x0, y0, x1, y1 = box
        x, y = round(x0 * sx), round(y0 * sy)
        return x, y, max(2, round(x1 * sx) - x), max(2, round(y1 * sy) - y)

    def dst(
        box: tuple[int, int, int, int], scale: float, x: int, y: int
    ) -> tuple[int, int, int, int]:
        x0, y0, x1, y1 = box
        w = max(2, round((x1 - x0) * scale * k))
        h = max(2, round((y1 - y0) * scale * k))
        return max(0, min(x, side - w)), max(0, min(y, side - h)), w, h

    minimap_dst = dst(
        layout.minimap_box,
        layout.minimap_scale,
        round(layout.minimap_x * k),
        round(layout.minimap_bottom * k)
        - round(
            (layout.minimap_box[3] - layout.minimap_box[1]) * layout.minimap_scale * k
        ),
    )
    kda_dst = dst(
        layout.kda_box,
        layout.kda_scale,
        round(layout.kda_x * k),
        round(layout.kda_y * k),
    )
    return ReelPlacement(
        side=side,
        crop_x=crop_x,
        minimap_src=src(layout.minimap_box),
        minimap_dst=minimap_dst,
        kda_src=src(layout.kda_box),
        kda_dst=kda_dst,
    )


def build_reel_filter(placement: ReelPlacement) -> str:
    """Build the ``-filter_complex`` graph that produces the square reel frame.

    The source is split three ways — once for the square crop and once for each
    rescued HUD region — then the two regions are scaled up and overlaid back
    onto the square. The result is exposed on the
    :data:`REEL_OUTPUT_LABEL` label for the caller to ``-map``.

    Args:
        placement: Geometry from :func:`plan_reel`.

    Returns:
        str: A single-line ffmpeg filter graph.
    """
    mx, my, mw, mh = placement.minimap_src
    mdx, mdy, mdw, mdh = placement.minimap_dst
    kx, ky, kw, kh = placement.kda_src
    kdx, kdy, kdw, kdh = placement.kda_dst
    side = placement.side
    return ";".join(
        [
            "[0:v]split=3[reel_base][reel_mm][reel_kda]",
            f"[reel_base]crop={side}:{side}:{placement.crop_x}:0[reel_sq]",
            f"[reel_mm]crop={mw}:{mh}:{mx}:{my},"
            f"scale={mdw}:{mdh}:flags=lanczos[reel_mm_s]",
            f"[reel_kda]crop={kw}:{kh}:{kx}:{ky},"
            f"scale={kdw}:{kdh}:flags=lanczos[reel_kda_s]",
            f"[reel_sq][reel_mm_s]overlay={mdx}:{mdy}[reel_o1]",
            f"[reel_o1][reel_kda_s]overlay={kdx}:{kdy}[{REEL_OUTPUT_LABEL}]",
        ]
    )


def reel_filter_for_video(
    video_path: str | Path, layout: ReelLayout | None = None
) -> str:
    """Convenience wrapper: probe ``video_path`` and build its reframe graph.

    Raises:
        ValueError: If the source is not landscape (see :func:`plan_reel`).
    """
    width, height = video_dimensions(video_path)
    return build_reel_filter(plan_reel(width, height, layout))
