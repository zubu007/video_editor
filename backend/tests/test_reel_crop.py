import unittest

from backend.features.gaming.reel_crop import (
    REEL_OUTPUT_LABEL,
    ReelLayout,
    build_reel_filter,
    plan_reel,
)


class TestPlanReel(unittest.TestCase):
    def test_centre_crop_at_calibrated_resolution(self):
        placement = plan_reel(1920, 1080)
        self.assertEqual(placement.side, 1080)
        # Equal bands off each side.
        self.assertEqual(placement.crop_x, 420)
        self.assertEqual(1920 - placement.crop_x - placement.side, 420)

    def test_hud_regions_come_from_the_discarded_left_band(self):
        placement = plan_reel(1920, 1080)
        for x, _y, w, _h in (placement.minimap_src, placement.kda_src):
            self.assertLessEqual(x + w, 420, "region must be outside the kept window")

    def test_overlay_sizes_and_positions_at_calibrated_resolution(self):
        placement = plan_reel(1920, 1080)
        # Minimap: 288x297 at 1.3x, bottom edge pinned to y=898.
        self.assertEqual(placement.minimap_dst, (10, 512, 374, 386))
        self.assertEqual(placement.minimap_dst[1] + placement.minimap_dst[3], 898)
        # K/D/A: 170x46 at 2x, clear of the top hero bar.
        self.assertEqual(placement.kda_dst, (18, 52, 340, 92))

    def test_overlays_stay_inside_the_square(self):
        for width, height in ((1920, 1080), (2560, 1440), (1280, 720)):
            placement = plan_reel(width, height)
            for x, y, w, h in (placement.minimap_dst, placement.kda_dst):
                self.assertGreaterEqual(x, 0)
                self.assertGreaterEqual(y, 0)
                self.assertLessEqual(x + w, placement.side)
                self.assertLessEqual(y + h, placement.side)

    def test_geometry_scales_with_resolution(self):
        placement = plan_reel(2560, 1440)
        self.assertEqual(placement.side, 1440)
        self.assertEqual(placement.crop_x, 560)
        # Everything is 4/3 of the calibrated numbers.
        self.assertEqual(placement.minimap_src, (0, 1044, 384, 396))
        self.assertEqual(placement.minimap_dst, (13, 682, 499, 515))
        # The pinned bottom edge scales too: 898 * 4/3.
        self.assertEqual(placement.minimap_dst[1] + placement.minimap_dst[3], 1197)

    def test_output_dimensions_are_even(self):
        # libx264 rejects odd dimensions; an odd-height source must round down.
        placement = plan_reel(1366, 769)
        self.assertEqual(placement.side % 2, 0)
        self.assertEqual(placement.crop_x % 2, 0)

    def test_portrait_source_is_rejected(self):
        with self.assertRaises(ValueError):
            plan_reel(1080, 1920)

    def test_square_source_is_rejected(self):
        with self.assertRaises(ValueError):
            plan_reel(1080, 1080)

    def test_custom_layout_is_honoured(self):
        layout = ReelLayout(kda_x=100, kda_y=200)
        placement = plan_reel(1920, 1080, layout)
        self.assertEqual(placement.kda_dst[:2], (100, 200))


class TestBuildReelFilter(unittest.TestCase):
    def test_filter_graph_wires_crop_and_both_overlays(self):
        graph = build_reel_filter(plan_reel(1920, 1080))
        self.assertIn("[0:v]split=3", graph)
        self.assertIn("crop=1080:1080:420:0", graph)
        self.assertIn("crop=288:297:0:783", graph)
        self.assertIn("scale=374:386", graph)
        self.assertIn("overlay=10:512", graph)
        self.assertIn("crop=170:46:0:56", graph)
        self.assertIn("scale=340:92", graph)
        self.assertIn("overlay=18:52", graph)
        self.assertTrue(graph.endswith(f"[{REEL_OUTPUT_LABEL}]"))

    def test_every_intermediate_label_is_consumed(self):
        graph = build_reel_filter(plan_reel(1920, 1080))
        produced = {
            "reel_base",
            "reel_mm",
            "reel_kda",
            "reel_sq",
            "reel_mm_s",
            "reel_kda_s",
            "reel_o1",
        }
        for label in produced:
            self.assertEqual(
                graph.count(f"[{label}]"), 2, f"{label} must be produced and consumed"
            )


if __name__ == "__main__":
    unittest.main()
