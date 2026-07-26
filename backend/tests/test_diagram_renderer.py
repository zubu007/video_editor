import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.features.diagram.renderer import (
    get_or_render_overlay,
    spec_cache_key,
)


def make_spec(**overrides):
    """Builds a minimal render spec, with optional overrides."""
    spec = {
        "diagram_type": "flowchart",
        "title": "Podcast workflow",
        "duration": 12.0,
        "graph": {
            "nodes": [
                {"id": "a", "label": "Record", "reveal_at": 1.0},
                {"id": "b", "label": "Edit"},
                {"id": "c", "label": "Publish"},
            ],
            "edges": [
                {"source": "a", "target": "b"},
                {"source": "b", "target": "c"},
            ],
            "reveal_order": ["a", "b", "c"],
        },
    }
    spec.update(overrides)
    return spec


class TestSpecCacheKey(unittest.TestCase):

    def test_stable_for_equal_specs(self):
        self.assertEqual(
            spec_cache_key(make_spec(), transparent=False, quality="low"),
            spec_cache_key(make_spec(), transparent=False, quality="low"),
        )

    def test_differs_by_spec_and_settings(self):
        base = spec_cache_key(make_spec(), transparent=False, quality="low")

        self.assertNotEqual(
            base, spec_cache_key(make_spec(title="Other"), False, "low")
        )
        self.assertNotEqual(
            base, spec_cache_key(make_spec(), transparent=True, quality="low")
        )
        self.assertNotEqual(
            base, spec_cache_key(make_spec(), transparent=False, quality="medium")
        )
        self.assertNotEqual(
            base, spec_cache_key(make_spec(layout="portrait"), False, "low")
        )


class TestGetOrRenderOverlay(unittest.TestCase):

    @patch("backend.features.diagram.renderer.render_diagram_video")
    def test_cache_miss_renders(self, mock_render):
        mock_render.side_effect = lambda spec, path, **kwargs: Path(path).touch()

        with TemporaryDirectory() as outdir:
            path, cached = get_or_render_overlay(make_spec(), outdir)

            self.assertFalse(cached)
            self.assertTrue(path.name.startswith("diagram_"))
            self.assertTrue(path.suffix == ".mp4")
            mock_render.assert_called_once()

    @patch("backend.features.diagram.renderer.render_diagram_video")
    def test_cache_hit_skips_render(self, mock_render):
        spec = make_spec()

        with TemporaryDirectory() as outdir:
            key = spec_cache_key(spec, transparent=True, quality="medium")
            (Path(outdir) / f"diagram_{key}.mov").touch()

            path, cached = get_or_render_overlay(
                spec, outdir, transparent=True, quality="medium"
            )

            self.assertTrue(cached)
            self.assertEqual(path.suffix, ".mov")
            mock_render.assert_not_called()


class TestSceneTiming(unittest.TestCase):
    """Layout/timing helpers from the Manim scene template.

    Importing the scene module needs manim installed; skip otherwise so the
    suite still runs in environments without the rendering dependency.
    """

    @classmethod
    def setUpClass(cls):
        try:
            from backend.features.diagram import manim_scenes
        except ImportError:
            raise unittest.SkipTest("manim is not installed")
        cls.scenes = manim_scenes

    def test_reveal_times_use_reveal_at_and_stay_increasing(self):
        nodes = [
            {"id": "a", "label": "A", "reveal_at": 2.0},
            {"id": "b", "label": "B", "reveal_at": 1.0},  # out of order on purpose
            {"id": "c", "label": "C"},
        ]

        times = self.scenes.reveal_times(nodes, ["a", "b", "c"], duration=12.0)

        self.assertAlmostEqual(times["a"], 2.0)
        # b's speech-synced time precedes a's, so it is pushed after a.
        self.assertGreater(times["b"], times["a"])
        self.assertGreater(times["c"], times["b"])
        self.assertLessEqual(max(times.values()), 12.0)

    def test_reveal_times_spread_evenly_without_reveal_at(self):
        nodes = [{"id": n, "label": n} for n in ("a", "b", "c")]

        times = self.scenes.reveal_times(nodes, ["a", "b", "c"], duration=10.0)

        self.assertLess(times["a"], times["b"])
        self.assertLess(times["b"], times["c"])

    def test_node_positions_shapes(self):
        for diagram_type in ("flowchart", "timeline", "comparison", "cycle"):
            for layout in ("landscape", "portrait"):
                positions = self.scenes.node_positions(diagram_type, 5, layout)
                self.assertEqual(len(positions), 5)

    def test_portrait_flowchart_is_a_single_column(self):
        positions = self.scenes.node_positions("flowchart", 5, layout="portrait")

        self.assertTrue(all(abs(pos[0]) < 1e-9 for pos in positions))
        ys = [pos[1] for pos in positions]
        self.assertEqual(ys, sorted(ys, reverse=True))  # top to bottom

    def test_timeline_axis_follows_layout(self):
        landscape = self.scenes.node_positions("timeline", 4, layout="landscape")
        portrait = self.scenes.node_positions("timeline", 4, layout="portrait")

        self.assertTrue(all(pos[1] == 0.0 for pos in landscape))
        self.assertTrue(all(pos[0] == 0.0 for pos in portrait))
        ys = [pos[1] for pos in portrait]
        self.assertEqual(ys, sorted(ys, reverse=True))  # top to bottom

    def test_portrait_cycle_is_taller_than_wide(self):
        positions = self.scenes.node_positions("cycle", 6, layout="portrait")

        xs = [pos[0] for pos in positions]
        ys = [pos[1] for pos in positions]
        self.assertGreater(max(ys) - min(ys), max(xs) - min(xs))


if __name__ == "__main__":
    unittest.main()
