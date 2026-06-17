import unittest

import numpy as np

from backend.features.face_detection.detect import (
    detect_face_center,
    find_largest_face,
)


class TestFaceDetection(unittest.TestCase):
    def test_blank_rgb_frame_has_no_face(self):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        self.assertIsNone(find_largest_face(frame))
        self.assertIsNone(detect_face_center(frame))

    def test_blank_grayscale_frame_has_no_face(self):
        frame = np.full((480, 640), 200, dtype=np.uint8)
        self.assertIsNone(find_largest_face(frame))

    def test_detect_face_center_returns_box_center(self):
        # Patch detection to a known box and verify the center math.
        from backend.features.face_detection import detect as detect_module

        original = detect_module.find_largest_face
        detect_module.find_largest_face = lambda frame: (100, 200, 40, 60)
        try:
            center = detect_module.detect_face_center(np.zeros((10, 10, 3)))
        finally:
            detect_module.find_largest_face = original

        self.assertEqual(center, (120.0, 230.0))


if __name__ == "__main__":
    unittest.main()
