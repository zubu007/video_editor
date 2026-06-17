"""Locate a face in a video frame to use as a zoom focus point.

Uses OpenCV's bundled Haar cascade classifier (CPU, no model download). The
largest detected face is treated as the subject of the shot; callers fall back
to the frame center when no face is found.
"""

from __future__ import annotations

import cv2
import numpy as np

# Lazily-instantiated shared classifier (loading the cascade XML is not free).
_face_cascade: cv2.CascadeClassifier | None = None


def _get_cascade() -> cv2.CascadeClassifier:
    """Return a shared frontal-face Haar cascade classifier."""
    global _face_cascade
    if _face_cascade is None:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _face_cascade = cv2.CascadeClassifier(cascade_path)
    return _face_cascade


def find_largest_face(frame: np.ndarray) -> tuple[int, int, int, int] | None:
    """Detect the largest face in a frame.

    Args:
        frame (np.ndarray): An ``HxWx3`` RGB image (as produced by MoviePy) or an
            ``HxW`` grayscale image.

    Returns:
        The ``(x, y, w, h)`` bounding box of the largest face in pixel
        coordinates, or ``None`` if no face is detected.
    """
    cascade = _get_cascade()
    if cascade.empty():
        return None

    if frame.ndim == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    else:
        gray = frame
    if gray.dtype != np.uint8:
        gray = gray.astype(np.uint8)

    faces = cascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
    )
    if len(faces) == 0:
        return None

    x, y, w, h = max(faces, key=lambda box: box[2] * box[3])
    return int(x), int(y), int(w), int(h)


def detect_face_center(frame: np.ndarray) -> tuple[float, float] | None:
    """Return the center of the largest face in a frame.

    Args:
        frame (np.ndarray): An RGB or grayscale image.

    Returns:
        The ``(x, y)`` pixel coordinates of the face center, or ``None`` if no
        face is detected.
    """
    box = find_largest_face(frame)
    if box is None:
        return None
    x, y, w, h = box
    return (x + w / 2.0, y + h / 2.0)
