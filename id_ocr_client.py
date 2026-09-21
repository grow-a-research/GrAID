"""
id_ocr_client.py — backend-side client for identification-answer OCR.

Sends identification crops to the GPU host's /ocr_id endpoint (whole box,
no line detection — see id_ocr.py), keeping them off the /ocr endpoint that
essays use. Falls back to ocr_pipeline.run_ocr_pipeline() whenever /ocr_id
isn't available, so a backend updated before the GPU host is re-uploaded
keeps working exactly as it did before.
"""
from __future__ import annotations

import io
import logging

import cv2
import numpy as np
import requests
from PIL import Image

import ocr_pipeline

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 180

# Ink (excluding the printed box borders) below which an answer box is empty.
# Qwen invents text for a blank crop rather than returning nothing, so an
# unanswered box would otherwise get a fabricated answer. Measured over 50
# real answers: the answer side of a box ran 1.08-6.26% dark pixels and the
# unwritten side 0.24-1.85%, with the faintest whole-box answer at 0.97%, so
# this sits below every real answer seen. A faint answer wrongly dropped
# still surfaces as an empty answer routed to teacher review, never as a
# confident wrong one.
_BLANK_BOX_INK_FRACTION = 0.004


def _ink_fraction(crop: Image.Image) -> float:
    """Fraction of dark pixels that aren't part of a printed rule/border."""
    gray = cv2.cvtColor(np.asarray(crop.convert("RGB")), cv2.COLOR_RGB2GRAY)
    otsu, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    binary = ((gray < max(60, otsu * 0.75)).astype(np.uint8)) * 255
    rule_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (int(25 * 300 / 25.4), 1))
    rules = cv2.morphologyEx(binary, cv2.MORPH_OPEN, rule_kernel)
    ink = cv2.subtract(binary, cv2.dilate(rules, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 7))))
    return float((ink > 0).mean())


def _fallback(crop: Image.Image) -> tuple[str, list[tuple[int, int, int, int]], bool]:
    text, boxes, _, low_conf = ocr_pipeline.run_ocr_pipeline(crop, include_boxed_image=False)
    return text, boxes, low_conf


def run_identification_ocr(
    crop: Image.Image,
) -> tuple[str, list[tuple[int, int, int, int]], bool]:
    """
    OCR one identification answer box.

    Returns (text, boxes, low_confidence) — the same three values the
    identification call sites use from run_ocr_pipeline(). `boxes` is the
    whole crop, since this path reads it as a single line.
    """
    ink = _ink_fraction(crop)
    if ink < _BLANK_BOX_INK_FRACTION:
        logger.info("Identification box is blank (%.2f%% ink) — skipping OCR", ink * 100)
        return "", [(0, 0, crop.width, crop.height)], False

    if not ocr_pipeline.REMOTE_OCR_URL:
        # No remote server configured: run locally if models are loaded,
        # otherwise let run_ocr_pipeline raise/behave as it always has.
        if ocr_pipeline.MODELS is None:
            return _fallback(crop)
        import id_ocr
        text, confidence = id_ocr.transcribe_answer_box(crop)
        return text, [(0, 0, crop.width, crop.height)], confidence < id_ocr.MIN_CONFIDENCE

    buf = io.BytesIO()
    crop.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    try:
        resp = requests.post(
            f"{ocr_pipeline.REMOTE_OCR_URL}/ocr_id",
            files={"file": ("image.png", buf, "image/png")},
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code == 404:
            # GPU host still runs a build without /ocr_id — use the shared
            # /ocr endpoint so identification keeps working until it's updated.
            logger.warning(
                "Remote OCR server has no /ocr_id endpoint — falling back to /ocr "
                "(upload id_ocr.py + vast_ocr_server.py and restart it to enable)"
            )
            return _fallback(crop)
        resp.raise_for_status()
    except requests.RequestException:
        raise

    data = resp.json()
    boxes = [tuple(b) for b in data.get("boxes", [])] or [(0, 0, crop.width, crop.height)]
    return data.get("text", ""), boxes, bool(data.get("low_confidence", False))
