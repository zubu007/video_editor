import unittest
from unittest.mock import Mock, patch

from backend.features.editing_plan.feature_registry import (
    get_feature_descriptions_for_llm,
    validate_feature_name,
    AVAILABLE_FEATURES,
)
from backend.features.editing_plan.generator import (
    generate_editing_plan,
    save_editing_plan,
    load_editing_plan,
    merge_editing_plans,
    filter_editing_plan_by_feature,
)


class TestFeatureRegistry(unittest.TestCase):

    def test_available_features_structure(self):
        """Test that all features have required fields."""
        for feature_id, feature in AVAILABLE_FEATURES.items():
            self.assertIn("name", feature)
            self.assertIn("description", feature)
            self.assertIn("use_case", feature)
            self.assertIn("parameters", feature)
            self.assertIsInstance(feature["parameters"], list)

    def test_get_feature_descriptions(self):
        """Test that feature descriptions are generated correctly."""
        descriptions = get_feature_descriptions_for_llm()
        self.assertIsInstance(descriptions, str)
        self.assertIn("zoom", descriptions)
        self.assertIn("text_overlay", descriptions)
        self.assertIn("insert_stock_footage", descriptions)

    def test_validate_feature_name(self):
        """Test feature name validation."""
        self.assertTrue(validate_feature_name("zoom"))
        self.assertTrue(validate_feature_name("text_overlay"))
        self.assertFalse(validate_feature_name("invalid_feature"))
        self.assertFalse(validate_feature_name(""))


class TestEditingPlanGenerator(unittest.TestCase):

    def setUp(self):
        """Set up test fixtures."""
        self.sample_transcript = [
            {"start": 0.0, "end": 3.5, "text": "Welcome to this podcast about AI."},
            {
                "start": 3.5,
                "end": 8.2,
                "text": "Today we will discuss neural networks.",
            },
            {"start": 8.2, "end": 12.0, "text": "Neural networks are fascinating."},
        ]

        self.sample_editing_plan = [
            {
                "start": 0.0,
                "end": 3.5,
                "feature": "text_overlay",
                "parameters": {"text": "AI Podcast", "style": "title"},
                "reason": "Opening statement",
            },
            {
                "start": 3.5,
                "end": 8.2,
                "feature": "zoom",
                "parameters": {"zoom_level": 1.2},
                "reason": "Emphasize key topic",
            },
        ]

    def test_merge_editing_plans(self):
        """Test merging multiple editing plans."""
        plan1 = [{"start": 0.0, "end": 2.0, "feature": "zoom", "parameters": {}}]
        plan2 = [
            {"start": 5.0, "end": 7.0, "feature": "text_overlay", "parameters": {}}
        ]
        plan3 = [{"start": 2.5, "end": 4.0, "feature": "transition", "parameters": {}}]

        merged = merge_editing_plans([plan1, plan2, plan3])

        self.assertEqual(len(merged), 3)
        # Check that it's sorted by start time
        self.assertEqual(merged[0]["start"], 0.0)
        self.assertEqual(merged[1]["start"], 2.5)
        self.assertEqual(merged[2]["start"], 5.0)

    def test_filter_editing_plan_by_feature(self):
        """Test filtering editing plan by feature names."""
        filtered = filter_editing_plan_by_feature(
            self.sample_editing_plan, ["text_overlay"]
        )

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["feature"], "text_overlay")

        # Test multiple features
        filtered_multi = filter_editing_plan_by_feature(
            self.sample_editing_plan, ["text_overlay", "zoom"]
        )

        self.assertEqual(len(filtered_multi), 2)

    def test_save_and_load_editing_plan(self):
        """Test saving and loading editing plans."""
        import tempfile
        import os

        # Create a temporary file
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            temp_file = f.name

        try:
            # Save the plan
            save_editing_plan(self.sample_editing_plan, temp_file)

            # Load the plan
            loaded_plan = load_editing_plan(temp_file)

            # Verify it matches
            self.assertEqual(loaded_plan, self.sample_editing_plan)
        finally:
            # Clean up
            if os.path.exists(temp_file):
                os.unlink(temp_file)

    @patch("backend.features.editing_plan.generator.EditingPlanLLM")
    def test_generate_editing_plan_with_mock(self, mock_llm_class):
        """Test editing plan generation with mocked LLM."""
        # Set up the mock
        mock_llm_instance = Mock()
        mock_llm_instance.generate_editing_plan.return_value = self.sample_editing_plan
        mock_llm_class.return_value = mock_llm_instance

        # Generate plan
        plan = generate_editing_plan(
            self.sample_transcript,
            api_key="test_key",
            model="llama-3.3-70b-versatile",
        )

        # Verify the LLM was called correctly
        mock_llm_class.assert_called_once_with(
            api_key="test_key", model="llama-3.3-70b-versatile"
        )
        mock_llm_instance.generate_editing_plan.assert_called_once()

        # Verify the result
        self.assertEqual(plan, self.sample_editing_plan)


class TestLLMClient(unittest.TestCase):

    def test_llm_client_requires_api_key(self):
        """Test that LLM client requires an API key."""
        from backend.features.editing_plan.llm_client import EditingPlanLLM

        # Clear the environment variable if it exists
        import os

        old_key = os.environ.pop("API_KEY", None)

        try:
            with self.assertRaises(ValueError) as context:
                EditingPlanLLM(api_key=None)

            self.assertIn("API key", str(context.exception))
        finally:
            # Restore the environment variable
            if old_key:
                os.environ["API_KEY"] = old_key

    def test_format_transcript(self):
        """Test transcript formatting for LLM."""
        from backend.features.editing_plan.llm_client import EditingPlanLLM

        # Create instance with dummy key
        llm = EditingPlanLLM(api_key="test_key")

        transcript = [
            {"start": 0.0, "end": 3.5, "text": "Hello world."},
            {"start": 3.5, "end": 7.0, "text": "This is a test."},
        ]

        formatted = llm._format_transcript(transcript)

        self.assertIn("[0.00s - 3.50s]", formatted)
        self.assertIn("Hello world.", formatted)
        self.assertIn("[3.50s - 7.00s]", formatted)
        self.assertIn("This is a test.", formatted)

    def test_validate_editing_plan(self):
        """Test editing plan validation."""
        from backend.features.editing_plan.llm_client import EditingPlanLLM

        llm = EditingPlanLLM(api_key="test_key")

        transcript = [{"start": 0.0, "end": 10.0, "text": "Test"}]

        # Valid plan
        valid_plan = [
            {
                "start": 0.0,
                "end": 5.0,
                "feature": "zoom",
                "parameters": {"zoom_level": 1.2},
            }
        ]

        validated = llm._validate_editing_plan(valid_plan, transcript)
        self.assertEqual(len(validated), 1)

        # Invalid plan - missing required fields
        invalid_plan_1 = [{"start": 0.0, "feature": "zoom"}]  # Missing 'end'

        validated = llm._validate_editing_plan(invalid_plan_1, transcript)
        self.assertEqual(len(validated), 0)

        # Invalid plan - invalid timestamps
        invalid_plan_2 = [
            {
                "start": 15.0,
                "end": 20.0,
                "feature": "zoom",
            }  # Beyond transcript duration
        ]

        validated = llm._validate_editing_plan(invalid_plan_2, transcript)
        self.assertEqual(len(validated), 0)

        # Invalid plan - invalid feature name
        invalid_plan_3 = [{"start": 0.0, "end": 5.0, "feature": "invalid_feature"}]

        validated = llm._validate_editing_plan(invalid_plan_3, transcript)
        self.assertEqual(len(validated), 0)

    def test_validate_stock_footage_with_search_query(self):
        """Test that stock footage requires search_query parameter."""
        from backend.features.editing_plan.llm_client import EditingPlanLLM

        llm = EditingPlanLLM(api_key="test_key")

        transcript = [{"start": 0.0, "end": 10.0, "text": "Test about nature"}]

        # Valid stock footage with search_query
        valid_stock_footage = [
            {
                "start": 0.0,
                "end": 5.0,
                "feature": "insert_stock_footage",
                "parameters": {"search_query": "nature forest"},
            }
        ]

        validated = llm._validate_editing_plan(valid_stock_footage, transcript)
        self.assertEqual(len(validated), 1)
        self.assertEqual(validated[0]["parameters"]["search_query"], "nature forest")

        # Invalid stock footage - missing search_query
        invalid_stock_footage_1 = [
            {
                "start": 0.0,
                "end": 5.0,
                "feature": "insert_stock_footage",
                "parameters": {},
            }
        ]

        validated = llm._validate_editing_plan(invalid_stock_footage_1, transcript)
        self.assertEqual(len(validated), 0)

        # Invalid stock footage - empty search_query
        invalid_stock_footage_2 = [
            {
                "start": 0.0,
                "end": 5.0,
                "feature": "insert_stock_footage",
                "parameters": {"search_query": "   "},
            }
        ]

        validated = llm._validate_editing_plan(invalid_stock_footage_2, transcript)
        self.assertEqual(len(validated), 0)

    def test_validate_stock_footage_media_type_and_duration(self):
        """Test media_type normalization and the attention-span duration caps."""
        from backend.features.editing_plan.llm_client import EditingPlanLLM

        llm = EditingPlanLLM(api_key="test_key")

        transcript = [{"start": 0.0, "end": 60.0, "text": "Test about nature"}]

        plan = [
            # Video B-roll over the 5s cap -> trimmed to 5s.
            {
                "start": 0.0,
                "end": 12.0,
                "feature": "insert_stock_footage",
                "parameters": {"search_query": "ocean waves", "media_type": "video"},
            },
            # Still image over the 3s cap -> trimmed to 3s.
            {
                "start": 20.0,
                "end": 30.0,
                "feature": "insert_stock_footage",
                "parameters": {"search_query": "mountain lake", "media_type": "image"},
            },
            # No media_type -> defaults to video; short span stays untouched.
            {
                "start": 40.0,
                "end": 42.0,
                "feature": "insert_stock_footage",
                "parameters": {"search_query": "city street"},
            },
            # Unknown media_type -> falls back to video.
            {
                "start": 50.0,
                "end": 51.0,
                "feature": "insert_stock_footage",
                "parameters": {"search_query": "forest", "media_type": "gif"},
            },
        ]

        validated = llm._validate_editing_plan(plan, transcript)
        self.assertEqual(len(validated), 4)

        self.assertEqual(validated[0]["parameters"]["media_type"], "video")
        self.assertAlmostEqual(validated[0]["end"], 5.0)

        self.assertEqual(validated[1]["parameters"]["media_type"], "image")
        self.assertAlmostEqual(validated[1]["end"], 23.0)

        self.assertEqual(validated[2]["parameters"]["media_type"], "video")
        self.assertAlmostEqual(validated[2]["end"], 42.0)

        self.assertEqual(validated[3]["parameters"]["media_type"], "video")
        self.assertAlmostEqual(validated[3]["end"], 51.0)


class TestStockMediaLimits(unittest.TestCase):
    """Tests for the attention-span helpers in the feature registry."""

    def test_clamp_stock_footage_end(self):
        from backend.features.editing_plan.feature_registry import (
            STOCK_MEDIA_MAX_SECONDS,
            clamp_stock_footage_end,
        )

        self.assertEqual(STOCK_MEDIA_MAX_SECONDS["video"], 5.0)
        self.assertEqual(STOCK_MEDIA_MAX_SECONDS["image"], 3.0)

        self.assertAlmostEqual(clamp_stock_footage_end(10.0, 30.0, "video"), 15.0)
        self.assertAlmostEqual(clamp_stock_footage_end(10.0, 30.0, "image"), 13.0)
        # A span within the limit is untouched.
        self.assertAlmostEqual(clamp_stock_footage_end(10.0, 12.0, "video"), 12.0)
        # Unknown media types clamp with the default (video) limit.
        self.assertAlmostEqual(clamp_stock_footage_end(0.0, 30.0, "hologram"), 5.0)

    def test_normalize_stock_media_type(self):
        from backend.features.editing_plan.feature_registry import (
            normalize_stock_media_type,
        )

        self.assertEqual(normalize_stock_media_type("image"), "image")
        self.assertEqual(normalize_stock_media_type(" Video "), "video")
        self.assertEqual(normalize_stock_media_type(None), "video")
        self.assertEqual(normalize_stock_media_type("gif"), "video")


if __name__ == "__main__":
    unittest.main()
