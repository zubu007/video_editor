"""Pluggable OCR engines for reading the Dota 2 K/D/A HUD counter.

The K/D/A pass originally ran on tesseract only; this module makes the engine
selectable (Settings → K/D/A detection) so different open-source OCRs can be
compared for accuracy on the small HUD digits. Three engines are supported:

- ``tesseract`` — classic CPU OCR via pytesseract (needs the system binary).
- ``paddleocr`` — PP-OCR deep-learning models (``uv pip install -e '.[ocr-paddle]'``).
- ``easyocr`` — PyTorch-based OCR (``uv pip install -e '.[ocr-easy]'``).

Engines are lazy: the heavy readers (PaddleOCR, EasyOCR) are imported and
initialised on first read and cached as process-wide singletons, while
availability checks are import-only so listing engines stays fast. All engines
share one contract: they receive the preprocessed K/D/A crop (upscaled,
binarised — dark digits on a white background) and return raw text, which the
caller parses with a digits regex. A read failure logs and returns ``""``
(treated as "no read" upstream) instead of killing the detection job.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from typing import Callable

import cv2
import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_OCR_ENGINE = "tesseract"

OCR_ENGINES: dict[str, dict[str, str]] = {
    "tesseract": {
        "label": "Tesseract",
        "description": (
            "Classic CPU OCR (pytesseract). Fast; requires the tesseract "
            "binary to be installed on the server."
        ),
    },
    "paddleocr": {
        "label": "PaddleOCR",
        "description": (
            "PP-OCR deep-learning models. Install on the server with: "
            "uv pip install -e '.[ocr-paddle]'"
        ),
    },
    "easyocr": {
        "label": "EasyOCR",
        "description": (
            "PyTorch-based OCR. Install on the server with: "
            "uv pip install -e '.[ocr-easy]'"
        ),
    },
}

# Loaded reader singletons (PaddleOCR / EasyOCR model init takes seconds and
# downloads weights on first use, so readers are created once per process).
_READERS: dict[str, object] = {}
_READER_LOCK = threading.Lock()


# ---------------------------------------------------------------- availability


def _tesseract_available() -> tuple[bool, str]:
    """Whether tesseract OCR can run, configuring pytesseract's binary path.

    The tesseract binary is often installed somewhere that isn't on the server
    process's ``PATH`` — most commonly Homebrew's ``/opt/homebrew/bin`` on macOS
    when the server is launched from a GUI or a minimal shell. When that happens
    ``pytesseract`` can't find the binary and OCR is silently disabled, which
    drops the K/A markers. We resolve the binary via ``shutil.which`` and a few
    well-known locations and point pytesseract at it so OCR isn't skipped purely
    because of ``PATH``.
    """
    try:
        import pytesseract
    except Exception:  # noqa: BLE001 - missing package disables the engine
        return False, "pytesseract is not installed"

    cmd = shutil.which("tesseract")
    if cmd is None:
        for candidate in (
            "/opt/homebrew/bin/tesseract",
            "/usr/local/bin/tesseract",
            "/usr/bin/tesseract",
        ):
            if os.path.exists(candidate):
                cmd = candidate
                break
    if cmd is not None:
        pytesseract.pytesseract.tesseract_cmd = cmd

    try:
        pytesseract.get_tesseract_version()
        return True, "ready"
    except Exception:  # noqa: BLE001 - any binary failure disables the engine
        return False, "the tesseract binary was not found on the server"


def _paddleocr_available() -> tuple[bool, str]:
    try:
        import paddleocr  # noqa: F401
    except Exception:  # noqa: BLE001 - missing/broken install disables the engine
        return False, "paddleocr is not installed"
    return True, "ready"


def _easyocr_available() -> tuple[bool, str]:
    try:
        import easyocr  # noqa: F401
    except Exception:  # noqa: BLE001 - missing/broken install disables the engine
        return False, "easyocr is not installed"
    return True, "ready"


_AVAILABILITY_CHECKS: dict[str, Callable[[], tuple[bool, str]]] = {
    "tesseract": _tesseract_available,
    "paddleocr": _paddleocr_available,
    "easyocr": _easyocr_available,
}


def engine_available(engine: str) -> tuple[bool, str]:
    """Return ``(available, detail)`` for an OCR engine.

    Args:
        engine: One of :data:`OCR_ENGINES`.

    Raises:
        ValueError: If ``engine`` is not a known engine name.
    """
    check = _AVAILABILITY_CHECKS.get(engine)
    if check is None:
        raise ValueError(
            f"Unknown OCR engine {engine!r}; known engines: "
            f"{', '.join(sorted(OCR_ENGINES))}"
        )
    return check()


def list_engines() -> list[dict]:
    """Describe every OCR engine for the settings UI.

    Returns:
        One dict per engine with ``name``, ``label``, ``description``,
        ``available`` and ``detail`` keys.
    """
    engines = []
    for name, meta in OCR_ENGINES.items():
        available, detail = engine_available(name)
        engines.append(
            {
                "name": name,
                "label": meta["label"],
                "description": meta["description"],
                "available": available,
                "detail": detail,
            }
        )
    return engines


# ---------------------------------------------------------------- readers


def _read_tesseract(bw: np.ndarray) -> str:
    import pytesseract

    return pytesseract.image_to_string(
        bw, config="--psm 7 -c tessedit_char_whitelist=0123456789/"
    )


def _get_paddle_reader():
    with _READER_LOCK:
        reader = _READERS.get("paddleocr")
        if reader is None:
            from paddleocr import PaddleOCR

            try:
                # PaddleOCR 3.x: document preprocessing stages off (the crop is
                # already a clean, upright strip).
                reader = PaddleOCR(
                    lang="en",
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                )
            except TypeError:
                # PaddleOCR 2.x kwargs.
                reader = PaddleOCR(lang="en", use_angle_cls=False, show_log=False)
            _READERS["paddleocr"] = reader
        return reader


def _paddle_texts(result: object) -> list[str]:
    """Extract recognised strings from either PaddleOCR 3.x or 2.x results."""
    texts: list[str] = []
    for page in result or []:
        if page is None:
            continue
        if hasattr(page, "get"):
            # 3.x predict(): dict-like result with parallel rec_texts list.
            texts.extend(str(t) for t in page.get("rec_texts") or [])
        elif isinstance(page, list):
            # 2.x ocr(): page is a list of [box, (text, confidence)] lines.
            for line in page:
                try:
                    texts.append(str(line[1][0]))
                except (TypeError, IndexError):
                    continue
    return texts


def _read_paddleocr(bw: np.ndarray) -> str:
    reader = _get_paddle_reader()
    bgr = cv2.cvtColor(bw, cv2.COLOR_GRAY2BGR) if bw.ndim == 2 else bw
    try:
        result = reader.predict(bgr)
    except AttributeError:
        result = reader.ocr(bgr, cls=False)
    return " ".join(_paddle_texts(result))


def _get_easyocr_reader():
    with _READER_LOCK:
        reader = _READERS.get("easyocr")
        if reader is None:
            import easyocr

            reader = easyocr.Reader(["en"], gpu=False, verbose=False)
            _READERS["easyocr"] = reader
        return reader


def _read_easyocr(bw: np.ndarray) -> str:
    reader = _get_easyocr_reader()
    results = reader.readtext(bw, allowlist="0123456789/", detail=0, paragraph=False)
    return " ".join(str(t) for t in results)


_READ_FUNCS: dict[str, Callable[[np.ndarray], str]] = {
    "tesseract": _read_tesseract,
    "paddleocr": _read_paddleocr,
    "easyocr": _read_easyocr,
}


def read_digits(engine: str, bw: np.ndarray) -> str:
    """Run one OCR engine over a preprocessed K/D/A crop and return raw text.

    Args:
        engine: One of :data:`OCR_ENGINES`.
        bw: Binarised crop (dark digits on white), single-channel uint8.

    Returns:
        The engine's raw text output, or ``""`` when the read fails (the
        caller treats an unparseable read as "carry the previous value").

    Raises:
        ValueError: If ``engine`` is not a known engine name.
    """
    func = _READ_FUNCS.get(engine)
    if func is None:
        raise ValueError(
            f"Unknown OCR engine {engine!r}; known engines: "
            f"{', '.join(sorted(OCR_ENGINES))}"
        )
    try:
        return func(bw)
    except Exception as e:  # noqa: BLE001 - a bad read must not kill the scan
        logger.warning("OCR read failed (engine=%s): %s", engine, e)
        return ""
