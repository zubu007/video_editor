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

    def test_reveal_at_kept_and_invalid_dropped(self):
        graph = validate_graph(
            make_graph(
                nodes=[
                    {"id": "a", "label": "Timed", "reveal_at": 2.5},
                    {"id": "b", "label": "Negative", "reveal_at": -1.0},
                    {"id": "c", "label": "Garbage", "reveal_at": "soon"},
                ],
                edges=[],
            )
        )

        by_id = {node["id"]: node for node in graph["nodes"]}
        self.assertEqual(by_id["a"]["reveal_at"], 2.5)
        self.assertNotIn("reveal_at", by_id["b"])
        self.assertNotIn("reveal_at", by_id["c"])


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

    def test_reveal_at_clamped_to_segment(self):
        nodes = [
            {"id": "a", "label": "Early", "reveal_at": 1.0},
            {"id": "b", "label": "Too late", "reveal_at": 99.0},
        ]
        result = validate_suggestion(
            make_suggestion(start=10.0, end=25.0, graph=make_graph(nodes=nodes)),
            total_duration=60.0,
        )

        by_id = {node["id"]: node for node in result["graph"]["nodes"]}
        self.assertEqual(by_id["a"]["reveal_at"], 1.0)
        # Clamped to duration (15s) minus the end-of-segment beat.
        self.assertEqual(by_id["b"]["reveal_at"], 14.0)

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


def make_section(**overrides):
    """Builds a minimal stage-1 detection section, with optional overrides."""
    section = {
        "start": 10.0,
        "end": 25.0,
        "diagram_type": "flowchart",
        "transcript_excerpt": "First you record, then you edit, then you publish.",
        "reason": "Speaker enumerates a three-step process.",
    }
    section.update(overrides)
    return section


def make_design(**overrides):
    """Builds a minimal stage-2 design response, with optional overrides."""
    design = {"title": "Podcast workflow", "graph": make_graph()}
    design.update(overrides)
    return design


def mock_json_response(payload):
    """Builds a mocked Groq chat completion returning ``payload`` as JSON."""
    import json

    return Mock(choices=[Mock(message=Mock(content=json.dumps(payload)))])


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

    def test_extract_list_formats(self):
        section = make_section()

        # {"sections": [...]} format
        self.assertEqual(
            DiagramDetectorLLM._extract_list({"sections": [section]}, "sections"),
            [section],
        )
        # Direct array format
        self.assertEqual(
            DiagramDetectorLLM._extract_list([section], "sections"), [section]
        )
        # First list found in an unexpected key
        self.assertEqual(
            DiagramDetectorLLM._extract_list({"results": [section]}, "sections"),
            [section],
        )
        # No list at all
        with self.assertRaises(ValueError):
            DiagramDetectorLLM._extract_list({"sections": "nope"}, "sections")

    @patch("backend.features.diagram.detector.Groq")
    def test_two_stage_suggest_diagrams(self, mock_groq_class):
        # Stage 1 finds two sections; stage 2 designs each in turn.
        detection = {"sections": [make_section(), make_section(start=30.0, end=45.0)]}
        create = mock_groq_class.return_value.chat.completions.create
        create.side_effect = [
            mock_json_response(detection),
            mock_json_response(make_design()),
            mock_json_response(make_design(title="Second diagram")),
        ]

        llm = DiagramDetectorLLM(api_key="test_key")
        transcript = [{"start": 0.0, "end": 60.0, "text": "Test"}]

        result = llm.suggest_diagrams(transcript)

        self.assertEqual(create.call_count, 3)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["start"], 10.0)
        self.assertEqual(result[0]["title"], "Podcast workflow")
        self.assertEqual(result[0]["graph"]["reveal_order"], ["a", "b", "c"])
        self.assertEqual(result[1]["title"], "Second diagram")

    @patch("backend.features.diagram.detector.Groq")
    def test_out_of_bounds_section_dropped(self, mock_groq_class):
        detection = {"sections": [make_section(), make_section(start=100.0, end=110.0)]}
        create = mock_groq_class.return_value.chat.completions.create
        create.side_effect = [
            mock_json_response(detection),
            mock_json_response(make_design()),
            mock_json_response(make_design()),
        ]

        llm = DiagramDetectorLLM(api_key="test_key")
        transcript = [{"start": 0.0, "end": 60.0, "text": "Test"}]

        result = llm.suggest_diagrams(transcript)

        # Both sections get designed, but the out-of-bounds one fails validation.
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["start"], 10.0)

    @patch("backend.features.diagram.detector.Groq")
    def test_failed_design_skips_section_only(self, mock_groq_class):
        detection = {"sections": [make_section(), make_section(start=30.0, end=45.0)]}
        create = mock_groq_class.return_value.chat.completions.create
        create.side_effect = [
            mock_json_response(detection),
            Exception("groq exploded"),  # first design call fails
            mock_json_response(make_design(title="Survivor")),
        ]

        llm = DiagramDetectorLLM(api_key="test_key")
        transcript = [{"start": 0.0, "end": 60.0, "text": "Test"}]

        result = llm.suggest_diagrams(transcript)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Survivor")

    @patch("backend.features.diagram.detector.Groq")
    def test_design_reveal_at_converted_to_segment_offsets(self, mock_groq_class):
        # The design stage answers on the transcript's clock; suggestions carry
        # offsets relative to the segment start.
        nodes = [
            {"id": "a", "label": "Record", "reveal_at": 12.0},
            {"id": "b", "label": "Edit", "reveal_at": 18.5},
            {"id": "c", "label": "Publish"},
        ]
        create = mock_groq_class.return_value.chat.completions.create
        create.side_effect = [
            mock_json_response({"sections": [make_section(start=10.0, end=25.0)]}),
            mock_json_response(make_design(graph=make_graph(nodes=nodes))),
        ]

        llm = DiagramDetectorLLM(api_key="test_key")
        transcript = [{"start": 0.0, "end": 60.0, "text": "Test"}]

        result = llm.suggest_diagrams(transcript)

        self.assertEqual(len(result), 1)
        by_id = {node["id"]: node for node in result[0]["graph"]["nodes"]}
        self.assertAlmostEqual(by_id["a"]["reveal_at"], 2.0)
        self.assertAlmostEqual(by_id["b"]["reveal_at"], 8.5)
        self.assertNotIn("reveal_at", by_id["c"])

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
