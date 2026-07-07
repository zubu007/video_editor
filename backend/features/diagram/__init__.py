"""Diagram feature: detect transcript segments suited to animated diagram overlays."""

from backend.features.diagram.detector import (
    DEFAULT_MODEL,
    DiagramDetectorLLM,
    suggest_diagrams,
)
from backend.features.diagram.schema import (
    DIAGRAM_TYPES,
    validate_graph,
    validate_suggestion,
    validate_suggestions,
)

__all__ = [
    "DEFAULT_MODEL",
    "DIAGRAM_TYPES",
    "DiagramDetectorLLM",
    "suggest_diagrams",
    "validate_graph",
    "validate_suggestion",
    "validate_suggestions",
]
