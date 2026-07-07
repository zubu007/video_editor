import unittest
from unittest.mock import Mock, patch

from backend.features.diagram.detector import DiagramDetectorLLM, suggest_diagrams
from backend.features.diagram.schema import (
    DEFAULT_DIAGRAM_TYPE,
    MAX_LABEL_LENGTH,
    MAX_NODES,
    MIN_DURATION_SECONDS,
    validate_graph,
    validate_suggestion,
    validate_suggestions,
)


def make_graph(**overrides):
    """Builds a minimal valid graph spec, with optional overrides."""
    graph = {
        "nodes": [
            {"id": "a", "label": "Record"},
            {"id": "b", "label": "Edit"},
            {"id": "c", "label": "Publish"},
        ],
        "edges": [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "c"},
        ],
        "reveal_order": ["a", "b", "c"],
    }
    graph.update(overrides)
    return graph


def make_suggestion(**overrides):
    """Builds a minimal valid suggestion, with optional overrides."""
    suggestion = {
        "start": 10.0,
        "end": 25.0,
        "diagram_type": "flowchart",
        "title": "Podcast workflow",
        "transcript_excerpt": "First you record, then you edit, then you publish.",
        "reason": "Speaker enumerates a three-step process.",
        "graph": make_graph(),
    }
    suggestion.update(overrides)
    return suggestion


class TestValidateGraph(unittest.TestCase):

    def test_valid_graph_passes_through(self):
        graph = validate_graph(make_graph())

        self.assertEqual(len(graph["nodes"]), 3)
        self.assertEqual(len(graph["edges"]), 2)
        self.assertEqual(graph["reveal_order"], ["a", "b", "c"])

    def test_graph_must_be_dict_with_node_list(self):
        with self.assertRaises(ValueError):
            validate_graph("not a dict")
        with self.assertRaises(ValueError):
            validate_graph({"nodes": "not a list"})

    def test_too_few_nodes_rejected(self):
        with self.assertRaises(ValueError):
            validate_graph(make_graph(nodes=[{"id": "a", "label": "Alone"}]))

    def test_too_many_nodes_rejected(self):
        nodes = [{"id": f"n{i}", "label": f"Step {i}"} for i in range(MAX_NODES + 1)]
        with self.assertRaises(ValueError):
            validate_graph(make_graph(nodes=nodes))

    def test_invalid_nodes_dropped(self):
        graph = validate_graph(
            make_graph(
                nodes=[
                    {"id": "a", "label": "Keep"},
                    {"id": "", "label": "No id"},
                    {"id": "b", "label": ""},
                    {"id": "a", "label": "Duplicate id"},
                    "not a dict",
                    {"id": "c", "label": "Keep too"},
                ]
            )
        )

        self.assertEqual([n["id"] for n in graph["nodes"]], ["a", "c"])
        self.assertEqual([n["label"] for n in graph["nodes"]], ["Keep", "Keep too"])

    def test_node_labels_truncated(self):
        long_label = "x" * (MAX_LABEL_LENGTH * 2)
        graph = validate_graph(
            make_graph(
                nodes=[
                    {"id": "a", "label": long_label},
                    {"id": "b", "label": "Short"},
                ],
                edges=[],
            )
        )

        self.assertLessEqual(len(graph["nodes"][0]["label"]), MAX_LABEL_LENGTH)
        self.assertTrue(graph["nodes"][0]["label"].endswith("…"))

    def test_bad_edges_dropped(self):
        graph = validate_graph(
            make_graph(
                edges=[
                    {"source": "a", "target": "b"},
                    {"source": "a", "target": "b"},  # duplicate
                    {"source": "a", "target": "a"},  # self-loop
                    {"source": "a", "target": "zzz"},  # unknown target
                    {"source": "", "target": "b"},  # missing source
                ]
            )
        )

        self.assertEqual(graph["edges"], [{"source": "a", "target": "b"}])

    def test_edges_accept_from_to_keys(self):
        graph = validate_graph(
            make_graph(edges=[{"from": "a", "to": "b", "label": "then"}])
        )

        self.assertEqual(
            graph["edges"], [{"source": "a", "target": "b", "label": "then"}]
        )

    def test_reveal_order_normalized(self):
        graph = validate_graph(
            make_graph(
                reveal_order=["b", "zzz", "b", "a"]
            )  # unknown + duplicate, "c" missing
        )

        self.assertEqual(graph["reveal_order"], ["b", "a", "c"])

    def test_missing_reveal_order_defaults_to_node_order(self):
        graph = validate_graph(make_graph(reveal_order=None))

        self.assertEqual(graph["reveal_order"], ["a", "b", "c"])


class TestValidateSuggestion(unittest.TestCase):

    def test_valid_suggestion(self):
        result = validate_suggestion(make_suggestion(), total_duration=60.0)

        self.assertEqual(result["start"], 10.0)
        self.assertEqual(result["end"], 25.0)
        self.assertEqual(result["diagram_type"], "flowchart")
        self.assertEqual(result["title"], "Podcast workflow")
        self.assertEqual(len(result["graph"]["nodes"]), 3)

    def test_missing_timestamps_rejected(self):
        with self.assertRaises(ValueError):
            validate_suggestion(make_suggestion(start=None), total_duration=60.0)

        bad = make_suggestion()
        del bad["end"]
        with self.assertRaises(ValueError):
            validate_suggestion(bad, total_duration=60.0)

    def test_out_of_bounds_timestamps_rejected(self):
        with self.assertRaises(ValueError):
            validate_suggestion(make_suggestion(start=-1.0), total_duration=60.0)
        with self.assertRaises(ValueError):
            validate_suggestion(make_suggestion(end=120.0), total_duration=60.0)
        with self.assertRaises(ValueError):
            validate_suggestion(
                make_suggestion(start=25.0, end=10.0), total_duration=60.0
            )

    def test_too_short_segment_rejected(self):
        end = 10.0 + MIN_DURATION_SECONDS / 2
        with self.assertRaises(ValueError):
            validate_suggestion(
                make_suggestion(start=10.0, end=end), total_duration=60.0
            )

    def test_unknown_diagram_type_falls_back(self):
        result = validate_suggestion(
            make_suggestion(diagram_type="mindmap"), total_duration=60.0
        )

        self.assertEqual(result["diagram_type"], DEFAULT_DIAGRAM_TYPE)

    def test_validate_suggestions_skips_invalid_and_sorts(self):
        suggestions = [
            make_suggestion(start=30.0, end=40.0),
            make_suggestion(start=100.0, end=110.0),  # beyond duration
            make_suggestion(start=5.0, end=15.0),
            make_suggestion(graph={"nodes": []}),  # unusable graph
        ]

        validated = validate_suggestions(suggestions, total_duration=60.0)

        self.assertEqual(len(validated), 2)
        self.assertEqual([s["start"] for s in validated], [5.0, 30.0])


class TestDiagramDetectorLLM(unittest.TestCase):

    def test_requires_api_key(self):
        import os

        old_key = os.environ.pop("API_KEY", None)
        try:
            with self.assertRaises(ValueError) as context:
                DiagramDetectorLLM(api_key=None)
            self.assertIn("API key", str(context.exception))
        finally:
            if old_key:
                os.environ["API_KEY"] = old_key

    def test_format_transcript(self):
        llm = DiagramDetectorLLM(api_key="test_key")

        transcript = [
            {"start": 0.0, "end": 3.5, "text": "Hello world."},
            {"start": 3.5, "end": 7.0, "text": "This is a test."},
        ]

        formatted = llm._format_transcript(transcript)

        self.assertIn("[0.00s - 3.50s]", formatted)
        self.assertIn("Hello world.", formatted)
        self.assertIn("[3.50s - 7.00s]", formatted)

    def test_extract_suggestions_formats(self):
        suggestion = make_suggestion()

        # {"diagrams": [...]} format
        self.assertEqual(
            DiagramDetectorLLM._extract_suggestions({"diagrams": [suggestion]}),
            [suggestion],
        )
        # Direct array format
        self.assertEqual(
            DiagramDetectorLLM._extract_suggestions([suggestion]), [suggestion]
        )
        # First list found in an unexpected key
        self.assertEqual(
            DiagramDetectorLLM._extract_suggestions({"results": [suggestion]}),
            [suggestion],
        )
        # No list at all
        with self.assertRaises(ValueError):
            DiagramDetectorLLM._extract_suggestions({"diagrams": "nope"})

    @patch("backend.features.diagram.detector.Groq")
    def test_suggest_diagrams_validates_llm_output(self, mock_groq_class):
        import json

        raw = {
            "diagrams": [
                make_suggestion(),
                make_suggestion(start=100.0, end=110.0),  # beyond duration → dropped
            ]
        }
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content=json.dumps(raw)))]
        mock_groq_class.return_value.chat.completions.create.return_value = (
            mock_response
        )

        llm = DiagramDetectorLLM(api_key="test_key")
        transcript = [{"start": 0.0, "end": 60.0, "text": "Test"}]

        result = llm.suggest_diagrams(transcript)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["start"], 10.0)
        self.assertEqual(result[0]["graph"]["reveal_order"], ["a", "b", "c"])

    @patch("backend.features.diagram.detector.DiagramDetectorLLM")
    def test_module_level_suggest_diagrams(self, mock_llm_class):
        mock_instance = Mock()
        mock_instance.suggest_diagrams.return_value = []
        mock_llm_class.return_value = mock_instance

        transcript = [{"start": 0.0, "end": 10.0, "text": "Test"}]
        result = suggest_diagrams(transcript, api_key="test_key", model="some-model")

        mock_llm_class.assert_called_once_with(api_key="test_key", model="some-model")
        mock_instance.suggest_diagrams.assert_called_once_with(transcript, "")
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
