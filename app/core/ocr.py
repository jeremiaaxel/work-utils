"""OCR engines — pluggable text detection + recognition.

`run()` returns the same region shape whichever engine is selected, chosen
at call time from the runtime settings (the Settings page). Two engines:

- ``paddle`` — PaddleOCR (the default; best Japanese accuracy).
- ``tesseract`` — self-hosted Tesseract; the private option, for when the
  page must not leave the machine. Needs the ``tesseract-ocr`` binary and
  the ``jpn``/``jpn_vert`` traineddata files installed on the host.

The paddle pipeline is the plain one rather than PPStructureV3 because it
reports bounding boxes in original image coordinates. PPStructureV3
recognises text per layout-region crop, so its boxes are local to each crop
and cannot be drawn over the page as-is.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import TYPE_CHECKING

from app.core import runtime_settings

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)

_ENGINE = None
_ORIENTATION_MODEL = None
_ENGINES = ("paddle", "tesseract")

# PaddleOCR's default is every core, which oversubscribes badly: one page
# cost 85 CPU-seconds on 16 threads but only 22 on one. A small cap is
# faster in practice and much cheaper on a small VPS.
_MAX_THREADS = 4


def selected_engine() -> str:
    """The engine the runtime settings name, validated against the registry."""
    name = runtime_settings.get_all().get("ocr_engine") or "paddle"
    return name if name in _ENGINES else "paddle"


def tesseract_available() -> bool:
    """True when the tesseract binary and Japanese data are installed."""
    if not shutil.which("tesseract"):
        return False
    try:
        langs = subprocess.run(
            ["tesseract", "--list-langs"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
    except Exception:
        return False
    return "jpn" in langs.split()


def _thread_count() -> int:
    return max(1, min(_MAX_THREADS, os.cpu_count() or 1))


def _build_engine():
    from paddleocr import PaddleOCR
    from paddlex.utils.deps import is_dep_available

    # paddlex gates its result types on this package — without it the OCR
    # result class raises on instantiation instead of failing on import.
    if not is_dep_available("opencv-contrib-python"):
        raise RuntimeError(
            "opencv-contrib-python is required for PaddleOCR "
            "(it ships with the paddleocr[all] extra)"
        )

    # Every preprocessor is disabled: each one would pull an extra model
    # (~10 MB each) that this tool has no use for.
    return PaddleOCR(
        lang="japan",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        cpu_threads=_thread_count(),
    )


def init_models() -> None:
    """Load the selected engine. Idempotent — safe to call on every startup."""
    global _ENGINE
    if _ENGINE is None and selected_engine() == "paddle":
        _ENGINE = _build_engine()
        logger.info("PaddleOCR engine ready")
    if selected_engine() == "paddle":
        init_orientation_model()


def init_orientation_model() -> None:
    """Load the page-orientation classifier. Idempotent."""
    global _ORIENTATION_MODEL
    if _ORIENTATION_MODEL is None:
        from paddlex import create_model

        _ORIENTATION_MODEL = create_model("PP-LCNet_x1_0_doc_ori")
        logger.info("Page orientation model ready")


def detect_orientation(image: np.ndarray) -> dict | None:
    """Guess which way up a page is.

    Returns ``{"angle": 0|90|180|270, "confidence": float}`` or None.

    Run standalone rather than through the OCR pipeline: the pipeline only
    exposes the angle and throws the confidence away, and it rotates the
    image under us, which would break the coordinate space our overlays
    depend on. Paddle-only — Tesseract has no equivalent model.
    """
    if selected_engine() != "paddle":
        return None
    init_orientation_model()
    assert _ORIENTATION_MODEL is not None
    for result in _ORIENTATION_MODEL.predict(image):
        angle = int(result["label_names"][0])
        confidence = float(result["scores"][0])
        return {"angle": angle, "confidence": round(confidence, 4)}
    return None


# ── engines ──────────────────────────────────────────────────────


def _run_paddle(image: np.ndarray) -> list[dict]:
    global _ENGINE
    init_models()
    engine = _ENGINE
    assert engine is not None
    regions: list[dict] = []
    for res in engine.predict(image):
        boxes, texts, scores = res["rec_boxes"], res["rec_texts"], res["rec_scores"]
        for box, text, score in zip(boxes, texts, scores):
            x1, y1, x2, y2 = (int(v) for v in box)
            regions.append(
                {
                    "bbox": (x1, y1, x2, y2),
                    "text": str(text),
                    "score": float(score),
                }
            )
    return regions


def _run_tesseract(image: np.ndarray) -> list[dict]:
    """Tesseract over a BGR array, one line per region.

    ``image_to_data`` walks the layout tree; level 5 is the text line.
    Vertical writing comes through ``jpn_vert`` (Tesseract 5's
    Japanese-vertical model); running both passes and keeping the lines
    with the better mean confidence covers both page styles.
    """
    import cv2
    import pytesseract
    from pytesseract import Output

    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    config = "--oem 1 --psm 3"

    best: dict[tuple[int, int, int, int], dict] = {}
    for lang in ("jpn", "jpn_vert"):
        try:
            data = pytesseract.image_to_data(
                rgb, lang=lang, config=config, output_type=Output.DICT
            )
        except pytesseract.TesseractError:
            continue  # the vertical model is optional
        for text, conf, left, top, width, height in zip(
            data["text"],
            data["conf"],
            data["left"],
            data["top"],
            data["width"],
            data["height"],
        ):
            text = (text or "").strip()
            try:
                score = float(conf)
            except (TypeError, ValueError):
                score = -1.0
            if not text or score < 0 or width <= 0 or height <= 0:
                continue
            box = (int(left), int(top), int(left + width), int(top + height))
            candidate = {"bbox": box, "text": text, "score": score / 100.0}
            previous = best.get(box)
            if previous is None or candidate["score"] > previous["score"]:
                best[box] = candidate

    return sorted(best.values(), key=lambda r: (r["bbox"][1], r["bbox"][0]))


_RUNNERS = {
    "paddle": _run_paddle,
    "tesseract": _run_tesseract,
}


def run(image: np.ndarray) -> list[dict]:
    """Run the selected engine over a BGR numpy array.

    Returns one region per detected text line:
    ``{"bbox": (x1, y1, x2, y2), "text": str, "score": float}``

    Coordinates are in the original image space. `image` must be a numpy
    array — an RGB array would swap the colour channels.
    """
    runner = _RUNNERS[selected_engine()]
    return runner(image)
