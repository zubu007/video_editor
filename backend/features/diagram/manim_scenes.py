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
)

BACKGROUND_COLOR = "#0f172a"
BOX_FILL = "#1e293b"
ACCENT = "#38bdf8"
EDGE_COLOR = "#94a3b8"

CONTENT_MAX_WIDTH = 12.4
CONTENT_MAX_HEIGHT = 5.4
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


def _cycle_positions(count: int, radius: float = 2.3) -> list[np.ndarray]:
    """Returns positions on a circle, clockwise from the top."""
    positions = []
    for index in range(count):
        theta = math.pi / 2 - index * 2 * math.pi / count
        positions.append(
            np.array([radius * 1.4 * math.cos(theta), radius * math.sin(theta), 0.0])
        )
    return positions


def node_positions(diagram_type: str, count: int) -> list[np.ndarray]:
    """Returns the layout positions for ``count`` nodes of ``diagram_type``."""
    if diagram_type == "cycle":
        return _cycle_positions(count)
    if diagram_type == "comparison":
        return _grid_positions(count, per_row=2, h_gap=4.8, v_gap=1.5)
    if diagram_type == "timeline":
        gap = min(2.9, CONTENT_MAX_WIDTH / max(count - 1, 1)) if count > 1 else 0.0
        return [np.array([(i - (count - 1) / 2) * gap, 0.0, 0.0]) for i in range(count)]
    # flowchart (default): rows of up to 4 steps
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
        if not spec.get("transparent"):
            self.camera.background_color = BACKGROUND_COLOR

        diagram_type = spec.get("diagram_type", "flowchart")
        duration = max(float(spec.get("duration", 8.0)), 3.0)
        graph = spec["graph"]
        nodes = graph["nodes"]
        edges = graph.get("edges", [])
        order = graph.get("reveal_order") or [node["id"] for node in nodes]

        positions = node_positions(diagram_type, len(nodes))
        node_mobs = {}
        for node, position in zip(nodes, positions):
            mob = self._node_mobject(diagram_type, node, position)
            node_mobs[node["id"]] = mob

        content = VGroup(*node_mobs.values())
        if diagram_type == "timeline" and len(nodes) > 1:
            xs = [pos[0] for pos in positions]
            baseline = Line(
                np.array([min(xs) - 0.7, 0.0, 0.0]),
                np.array([max(xs) + 0.7, 0.0, 0.0]),
                color=EDGE_COLOR,
                stroke_width=3,
            )
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

        if content.width > CONTENT_MAX_WIDTH:
            content.scale_to_fit_width(CONTENT_MAX_WIDTH)
        if content.height > CONTENT_MAX_HEIGHT:
            content.scale_to_fit_height(CONTENT_MAX_HEIGHT)
        content.move_to(DOWN * 0.4)

        title = None
        if spec.get("title"):
            title = Text(spec["title"], font_size=40, color=WHITE, weight="BOLD")
            if title.width > CONTENT_MAX_WIDTH:
                title.scale_to_fit_width(CONTENT_MAX_WIDTH)
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

    def _node_mobject(self, diagram_type: str, node: dict, position: np.ndarray):
        """Builds the mobject for one node at its layout position."""
        if diagram_type == "timeline":
            dot = Dot(point=position, radius=0.11, color=ACCENT)
            label = Text(node["label"], font_size=24, color=WHITE)
            if label.width > 2.4:
                label.scale_to_fit_width(2.4)
            index = int(abs(position[0] * 10))  # stable above/below alternation
            direction = UP if index % 2 == 0 else DOWN
            label.next_to(dot, direction, buff=0.35)
            return VGroup(dot, label)

        label = Text(node["label"], font_size=26, color=WHITE)
        if label.width > 2.6:
            label.scale_to_fit_width(2.6)
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
        if text.width > 1.8:
            text.scale_to_fit_width(1.8)
        text.move_to(arrow.get_center() + UP * 0.28)
        return VGroup(arrow, text)
