"""Manim scene template that renders a validated diagram spec.

This module is executed by the Manim CLI in a subprocess (see
``backend.features.diagram.renderer``), never imported by the API process —
Manim is a heavy dependency and its import configures global state. The scene
reads a spec JSON file from the ``DIAGRAM_SPEC_PATH`` environment variable:

    {
      "diagram_type": "flowchart" | "timeline" | "comparison" | "cycle",
      "title": "...",
      "duration": <seconds>,
      "transparent": <bool>,
      "background": "#rrggbb",   # optional solid background; wins over the
                                 # transparent flag's default dark fill
      "layout": "landscape" | "portrait",   # frame orientation (default landscape)
      "graph": {
        "nodes": [{"id", "label", "reveal_at"?}, ...],   # reveal_at is an
        "edges": [{"source", "target", "label"?}, ...],  # offset from 0
        "reveal_order": ["id", ...]
      }
    }

The spec is trusted to be schema-validated; the layout code here is entirely
deterministic — the LLM never emits drawing code, only the graph above.
"""

from __future__ import annotations

import json
import math
import os

import numpy as np
from manim import (
    DOWN,
    LEFT,
    RIGHT,
    UP,
    WHITE,
    Arrow,
    Create,
    CurvedArrow,
    Dot,
    FadeIn,
    GrowFromCenter,
    Line,
    RoundedRectangle,
    Scene,
    Text,
    VGroup,
    config,
)

BACKGROUND_COLOR = "#0f172a"
BOX_FILL = "#1e293b"
ACCENT = "#38bdf8"
EDGE_COLOR = "#94a3b8"

DEFAULT_LAYOUT = "landscape"
# Usable content area (width, height) in frame units, per orientation. The
# landscape frame is 14.2x8; the portrait frame is ~4.5x8 (see the config
# block below), both minus the title band at the top.
CONTENT_LIMITS = {
    "landscape": (12.4, 5.4),
    "portrait": (4.1, 6.2),
}
REVEAL_RUN_TIME = 0.5
REVEAL_LEAD = 0.8
REVEAL_TAIL = 1.2
REVEAL_MIN_GAP = 0.35


def _load_spec() -> dict:
    """Loads the diagram spec pointed to by ``DIAGRAM_SPEC_PATH``."""
    spec_path = os.environ.get("DIAGRAM_SPEC_PATH")
    if not spec_path:
        raise RuntimeError("DIAGRAM_SPEC_PATH environment variable is not set")
    with open(spec_path, encoding="utf-8") as handle:
        return json.load(handle)


# Portrait renders rotate the frame at import time: the quality preset's pixel
# dimensions are swapped and the frame width shrinks to match. Module-level
# config wins over CLI flags because Manim imports this file after digesting
# them. Guarded by the env var so importing this module for unit tests (no
# spec) stays side-effect free.
if os.environ.get("DIAGRAM_SPEC_PATH"):
    if _load_spec().get("layout") == "portrait":
        config.pixel_width, config.pixel_height = (
            min(config.pixel_width, config.pixel_height),
            max(config.pixel_width, config.pixel_height),
        )
        config.frame_width = (
            config.frame_height * config.pixel_width / config.pixel_height
        )


def _grid_positions(
    count: int, per_row: int, h_gap: float, v_gap: float
) -> list[np.ndarray]:
    """Returns row-major grid positions centered on the origin."""
    rows = math.ceil(count / per_row)
    positions = []
    for index in range(count):
        row, col = divmod(index, per_row)
        row_count = min(per_row, count - row * per_row)
        x = (col - (row_count - 1) / 2) * h_gap
        y = ((rows - 1) / 2 - row) * v_gap
        positions.append(np.array([x, y, 0.0]))
    return positions


def _cycle_positions(count: int, portrait: bool = False) -> list[np.ndarray]:
    """Returns positions on an ellipse, clockwise from the top.

    The ellipse is stretched along the frame's long axis: horizontally in
    landscape, vertically in portrait.
    """
    x_radius, y_radius = (1.6, 2.7) if portrait else (3.2, 2.3)
    positions = []
    for index in range(count):
        theta = math.pi / 2 - index * 2 * math.pi / count
        positions.append(
            np.array([x_radius * math.cos(theta), y_radius * math.sin(theta), 0.0])
        )
    return positions


def node_positions(
    diagram_type: str, count: int, layout: str = DEFAULT_LAYOUT
) -> list[np.ndarray]:
    """Returns the layout positions for ``count`` nodes of ``diagram_type``.

    Args:
        diagram_type: One of flowchart, timeline, comparison, cycle.
        count: Number of nodes to place.
        layout: "landscape" (default) or "portrait"; portrait variants stack
            along the vertical axis instead of the horizontal one.
    """
    portrait = layout == "portrait"
    if diagram_type == "cycle":
        return _cycle_positions(count, portrait=portrait)
    if diagram_type == "comparison":
        if portrait:
            return _grid_positions(count, per_row=2, h_gap=2.2, v_gap=1.3)
        return _grid_positions(count, per_row=2, h_gap=4.8, v_gap=1.5)
    if diagram_type == "timeline":
        # Nodes spread along the frame's long axis around the origin.
        max_span, cap = (
            (CONTENT_LIMITS["portrait"][1], 1.9)
            if portrait
            else (CONTENT_LIMITS["landscape"][0], 2.9)
        )
        gap = min(cap, max_span / max(count - 1, 1)) if count > 1 else 0.0
        if portrait:
            return [
                np.array([0.0, ((count - 1) / 2 - i) * gap, 0.0]) for i in range(count)
            ]
        return [np.array([(i - (count - 1) / 2) * gap, 0.0, 0.0]) for i in range(count)]
    # flowchart (default): rows of up to 4 steps, or one column in portrait
    if portrait:
        return _grid_positions(count, per_row=1, h_gap=0.0, v_gap=1.4)
    return _grid_positions(count, per_row=4, h_gap=3.3, v_gap=1.8)


def reveal_times(nodes: list[dict], reveal_order: list[str], duration: float) -> dict:
    """Computes when each node appears, in seconds from the segment start.

    A node's own ``reveal_at`` (speech-synced, from the LLM) wins when present;
    otherwise nodes are spread evenly across the segment. Times are clamped
    into the segment and forced to be increasing along ``reveal_order``.
    """
    by_id = {node["id"]: node for node in nodes}
    order = [node_id for node_id in reveal_order if node_id in by_id] or [
        node["id"] for node in nodes
    ]

    latest = max(duration - REVEAL_TAIL, REVEAL_LEAD)
    span = latest - REVEAL_LEAD
    times: dict[str, float] = {}
    for index, node_id in enumerate(order):
        default = REVEAL_LEAD + span * index / max(len(order) - 1, 1)
        raw = by_id[node_id].get("reveal_at")
        t = float(raw) if raw is not None else default
        times[node_id] = min(max(t, REVEAL_LEAD), latest)

    previous = None
    for node_id in order:
        if previous is not None:
            times[node_id] = max(times[node_id], times[previous] + REVEAL_MIN_GAP)
        previous = node_id
    return times


class DiagramScene(Scene):
    """Renders one validated diagram spec as an animated overlay."""

    def construct(self):
        spec = _load_spec()
        if spec.get("background"):
            self.camera.background_color = spec["background"]
        elif not spec.get("transparent"):
            self.camera.background_color = BACKGROUND_COLOR

        diagram_type = spec.get("diagram_type", "flowchart")
        layout = spec.get("layout", DEFAULT_LAYOUT)
        max_width, max_height = CONTENT_LIMITS.get(
            layout, CONTENT_LIMITS[DEFAULT_LAYOUT]
        )
        duration = max(float(spec.get("duration", 8.0)), 3.0)
        graph = spec["graph"]
        nodes = graph["nodes"]
        edges = graph.get("edges", [])
        order = graph.get("reveal_order") or [node["id"] for node in nodes]

        positions = node_positions(diagram_type, len(nodes), layout)
        node_mobs = {}
        for index, (node, position) in enumerate(zip(nodes, positions)):
            mob = self._node_mobject(diagram_type, node, position, layout, index)
            node_mobs[node["id"]] = mob

        content = VGroup(*node_mobs.values())
        if diagram_type == "timeline" and len(nodes) > 1:
            # The baseline runs along the frame's long axis, past the end dots.
            axis = 1 if layout == "portrait" else 0
            values = [pos[axis] for pos in positions]
            start, end = np.zeros(3), np.zeros(3)
            start[axis], end[axis] = min(values) - 0.7, max(values) + 0.7
            baseline = Line(start, end, color=EDGE_COLOR, stroke_width=3)
            content.add(baseline)
        else:
            baseline = None

        edge_mobs = []
        if diagram_type != "timeline":
            for edge in edges:
                source = node_mobs.get(edge["source"])
                target = node_mobs.get(edge["target"])
                if source is None or target is None:
                    continue
                mob = self._edge_mobject(
                    source, target, edge.get("label"), curved=diagram_type == "cycle"
                )
                edge_mobs.append((edge, mob))
                content.add(mob)

        if content.width > max_width:
            content.scale_to_fit_width(max_width)
        if content.height > max_height:
            content.scale_to_fit_height(max_height)
        content.move_to(DOWN * 0.4)

        title = None
        if spec.get("title"):
            title = Text(spec["title"], font_size=40, color=WHITE, weight="BOLD")
            if title.width > max_width:
                title.scale_to_fit_width(max_width)
            title.to_edge(UP, buff=0.45)

        times = reveal_times(nodes, order, duration)
        events: list[tuple[float, list]] = []
        if title is not None:
            events.append((0.2, [FadeIn(title)]))
        if baseline is not None:
            events.append((0.4, [Create(baseline)]))
        for node_id, mob in node_mobs.items():
            animations = [GrowFromCenter(mob)]
            for edge, edge_mob in edge_mobs:
                # An edge appears together with the later of its endpoints.
                later = max(
                    times.get(edge["source"], 0.0), times.get(edge["target"], 0.0)
                )
                if times.get(node_id) == later and node_id in (
                    edge["source"],
                    edge["target"],
                ):
                    animations.append(Create(edge_mob))
            events.append((times.get(node_id, REVEAL_LEAD), animations))

        now = 0.0
        for at, animations in sorted(events, key=lambda item: item[0]):
            if at > now:
                self.wait(at - now)
                now = at
            self.play(*animations, run_time=REVEAL_RUN_TIME)
            now += REVEAL_RUN_TIME
        if duration > now:
            self.wait(duration - now)

    def _node_mobject(
        self,
        diagram_type: str,
        node: dict,
        position: np.ndarray,
        layout: str = DEFAULT_LAYOUT,
        index: int = 0,
    ):
        """Builds the mobject for one node at its layout position."""
        portrait = layout == "portrait"
        if diagram_type == "timeline":
            dot = Dot(point=position, radius=0.11, color=ACCENT)
            label = Text(node["label"], font_size=24, color=WHITE)
            max_label = 1.7 if portrait else 2.4
            if label.width > max_label:
                label.scale_to_fit_width(max_label)
            # Labels alternate across the baseline: above/below in landscape,
            # left/right in portrait.
            if portrait:
                direction = LEFT if index % 2 == 0 else RIGHT
            else:
                direction = UP if index % 2 == 0 else DOWN
            label.next_to(dot, direction, buff=0.35)
            return VGroup(dot, label)

        label = Text(node["label"], font_size=26, color=WHITE)
        # Cap label width so boxes stay clear of their horizontal neighbors:
        # portrait comparison columns are 2.2 apart, a portrait flowchart is a
        # single full-width column, landscape grids are 3.3+ apart.
        if portrait:
            max_label = 1.4 if diagram_type == "comparison" else 3.2
        else:
            max_label = 2.6
        if label.width > max_label:
            label.scale_to_fit_width(max_label)
        box = RoundedRectangle(
            corner_radius=0.15,
            width=max(label.width + 0.55, 1.7),
            height=label.height + 0.5,
            fill_color=BOX_FILL,
            fill_opacity=0.92,
            stroke_color=ACCENT,
            stroke_width=2.5,
        )
        box.move_to(position)
        label.move_to(position)
        return VGroup(box, label)

    @staticmethod
    def _anchor_point(mob, direction: np.ndarray) -> np.ndarray:
        """Point where a ray from ``mob``'s center exits its bounding box.

        Manim's ``get_boundary_point`` returns an outline vertex, which for a
        box's flat edge can be a corner — skewing arrows between horizontally
        aligned nodes. Intersecting the bounding box directly keeps arrows
        centered on the faces they leave/enter.
        """
        half_w, half_h = mob.width / 2, mob.height / 2
        scale = min(
            half_w / abs(direction[0]) if abs(direction[0]) > 1e-6 else math.inf,
            half_h / abs(direction[1]) if abs(direction[1]) > 1e-6 else math.inf,
        )
        return mob.get_center() + direction * scale

    def _edge_mobject(self, source, target, label: str | None, curved: bool):
        """Builds an arrow (optionally labelled) between two node mobjects."""
        offset = target.get_center() - source.get_center()
        distance = np.linalg.norm(offset)
        direction = offset / distance if distance > 1e-6 else np.array([1.0, 0.0, 0.0])
        start = self._anchor_point(source, direction) + direction * 0.12
        end = self._anchor_point(target, -direction) - direction * 0.12

        if curved:
            arrow = CurvedArrow(
                start, end, angle=-0.7, color=EDGE_COLOR, stroke_width=3, tip_length=0.2
            )
        else:
            arrow = Arrow(
                start,
                end,
                buff=0.0,
                color=EDGE_COLOR,
                stroke_width=3,
                max_tip_length_to_length_ratio=0.12,
            )

        if not label:
            return arrow
        text = Text(label, font_size=18, color=EDGE_COLOR)
        if curved or abs(direction[0]) >= abs(direction[1]):
            # Above the shaft. Straight labels shrink to the gap the arrow
            # spans so they don't overhang the endpoint boxes; curved labels
            # sit off the chord, so the generous cap is enough.
            max_width = (
                1.8
                if curved
                else max(min(1.8, float(np.linalg.norm(end - start)) - 0.1), 0.4)
            )
            if text.width > max_width:
                text.scale_to_fit_width(max_width)
            text.move_to(arrow.get_center() + UP * 0.28)
        else:
            # Mostly-vertical arrows (portrait flowcharts, grid rows): place
            # the label beside the shaft so it clears the endpoint boxes.
            if text.width > 1.8:
                text.scale_to_fit_width(1.8)
            text.move_to(arrow.get_center() + RIGHT * (text.width / 2 + 0.22))
        return VGroup(arrow, text)
