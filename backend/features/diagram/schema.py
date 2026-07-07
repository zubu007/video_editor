"""Graph-spec schema and validation for diagram suggestions.

The diagram feature never executes LLM-generated code. The LLM emits a
constrained graph spec (nodes, edges, reveal order) and this module is the
single gatekeeper that turns that raw output into specs the renderer and the
rest of the pipeline can trust.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

DIAGRAM_TYPES = ("flowchart", "timeline", "comparison", "cycle")
DEFAULT_DIAGRAM_TYPE = "flowchart"

MIN_NODES = 2
MAX_NODES = 10
MAX_EDGES = 15
MAX_LABEL_LENGTH = 48
MAX_TITLE_LENGTH = 80
MIN_DURATION_SECONDS = 3.0


def _clean_label(value: Any, max_length: int = MAX_LABEL_LENGTH) -> str:
    """Coerces a value to a stripped string capped at ``max_length``.

    Args:
        value: Raw value from the LLM (may be None or non-string).
        max_length: Maximum length; longer text is truncated with an ellipsis.

    Returns:
        str: Cleaned label, possibly empty.
    """
    text = str(value).strip() if value is not None else ""
    if len(text) > max_length:
        text = text[: max_length - 1].rstrip() + "…"
    return text


def validate_graph(graph: dict) -> dict:
    """Validates and normalizes a raw graph spec from the LLM.

    Nodes with missing/duplicate ids or empty labels are dropped. Edges are
    dropped when they reference unknown nodes, are self-loops, or duplicate an
    earlier edge; both ``source``/``target`` and ``from``/``to`` key styles are
    accepted. ``reveal_order`` is filtered to known ids, deduplicated, and any
    missing nodes are appended in declaration order.

    Args:
        graph: Raw graph dict with "nodes", "edges" and "reveal_order" keys.

    Returns:
        dict: Normalized graph with "nodes", "edges" and "reveal_order".

    Raises:
        ValueError: If the graph is structurally unusable (not a dict, or the
            cleaned node count falls outside [MIN_NODES, MAX_NODES]).
    """
    if not isinstance(graph, dict):
        raise ValueError("graph must be an object")

    raw_nodes = graph.get("nodes")
    if not isinstance(raw_nodes, list):
        raise ValueError("graph.nodes must be a list")

    nodes: list[dict] = []
    seen_ids: set[str] = set()
    for raw in raw_nodes:
        if not isinstance(raw, dict):
            continue
        node_id = str(raw.get("id") or "").strip()
        label = _clean_label(raw.get("label"))
        if not node_id or not label or node_id in seen_ids:
            continue
        seen_ids.add(node_id)
        nodes.append({"id": node_id, "label": label})

    if len(nodes) < MIN_NODES:
        raise ValueError(f"graph needs at least {MIN_NODES} valid nodes")
    if len(nodes) > MAX_NODES:
        raise ValueError(f"graph exceeds the {MAX_NODES}-node limit")

    edges: list[dict] = []
    seen_edges: set[tuple[str, str]] = set()
    for raw in graph.get("edges") or []:
        if not isinstance(raw, dict):
            continue
        source = str(raw.get("source") or raw.get("from") or "").strip()
        target = str(raw.get("target") or raw.get("to") or "").strip()
        if source not in seen_ids or target not in seen_ids or source == target:
            continue
        if (source, target) in seen_edges:
            continue
        if len(edges) >= MAX_EDGES:
            logger.warning("Dropping edges beyond the %d-edge limit", MAX_EDGES)
            break
        seen_edges.add((source, target))
        edge: dict = {"source": source, "target": target}
        label = _clean_label(raw.get("label"))
        if label:
            edge["label"] = label
        edges.append(edge)

    reveal_order: list[str] = []
    for raw_id in graph.get("reveal_order") or []:
        node_id = str(raw_id).strip()
        if node_id in seen_ids and node_id not in reveal_order:
            reveal_order.append(node_id)
    reveal_order.extend(node["id"] for node in nodes if node["id"] not in reveal_order)

    return {"nodes": nodes, "edges": edges, "reveal_order": reveal_order}


def validate_suggestion(suggestion: dict, total_duration: float) -> dict:
    """Validates and normalizes a single diagram suggestion.

    Args:
        suggestion: Raw suggestion dict from the LLM.
        total_duration: Video duration in seconds; timestamps must fit inside.

    Returns:
        dict: Normalized suggestion with "start", "end", "diagram_type",
            "title", "transcript_excerpt", "reason" and "graph" keys.

    Raises:
        ValueError: If timestamps are missing/out of bounds, the segment is
            shorter than MIN_DURATION_SECONDS, or the graph is unusable.
    """
    if not isinstance(suggestion, dict):
        raise ValueError("suggestion must be an object")

    try:
        start = float(suggestion["start"])
        end = float(suggestion["end"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("suggestion needs numeric 'start' and 'end'")

    if start < 0 or end > total_duration or start >= end:
        raise ValueError(f"timestamps out of bounds: {start:.2f}-{end:.2f}")
    if end - start < MIN_DURATION_SECONDS:
        raise ValueError(
            f"segment shorter than {MIN_DURATION_SECONDS}s: {start:.2f}-{end:.2f}"
        )

    diagram_type = str(suggestion.get("diagram_type") or "").strip().lower()
    if diagram_type not in DIAGRAM_TYPES:
        logger.warning(
            "Unknown diagram_type %r, falling back to %r",
            diagram_type,
            DEFAULT_DIAGRAM_TYPE,
        )
        diagram_type = DEFAULT_DIAGRAM_TYPE

    graph = validate_graph(suggestion.get("graph") or {})

    return {
        "start": start,
        "end": end,
        "diagram_type": diagram_type,
        "title": _clean_label(suggestion.get("title"), MAX_TITLE_LENGTH),
        "transcript_excerpt": str(suggestion.get("transcript_excerpt") or "").strip(),
        "reason": str(suggestion.get("reason") or "").strip(),
        "graph": graph,
    }


def validate_suggestions(suggestions: list, total_duration: float) -> list:
    """Validates a list of raw suggestions, skipping unusable ones.

    Args:
        suggestions: Raw suggestion dicts from the LLM.
        total_duration: Video duration in seconds.

    Returns:
        list: Validated suggestions sorted by start time.
    """
    validated = []
    for suggestion in suggestions:
        try:
            validated.append(validate_suggestion(suggestion, total_duration))
        except ValueError as exc:
            logger.warning("Skipping diagram suggestion: %s", exc)
    validated.sort(key=lambda item: item["start"])
    return validated
