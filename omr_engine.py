"""
omr_engine.py — Phase 13: OMR bubble fill detection.

Given a perspective-corrected (warped) exam scan and the bubble positions
stored in region_json, determines which bubble the student filled.

Algorithm
---------
1. Convert the warped image to grayscale.
2. Apply Otsu thresholding → binary image (filled marks = white after INV).
3. For each bubble circle defined in region_json["bubbles"]:
   - Build a circular pixel mask centred on the bubble.
   - Compute fill ratio = (dark/filled pixels inside circle) / (total circle pixels).
4. Return the label with the highest fill ratio above MIN_FILL_RATIO.
5. confidence = (best_ratio - second_best_ratio) / best_ratio.
   Values below LOW_CONFIDENCE_THRESHOLD are flagged for teacher review.
"""
from __future__ import annotations

import logging
from typing import Any

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

MM_PER_INCH: float = 25.4

# A bubble must have at least this fraction of its area filled to count
MIN_FILL_RATIO: float = 0.12

# Below this gap-based confidence the result is flagged for review
LOW_CONFIDENCE_THRESHOLD: float = 0.30


def _mm_to_px(mm: float, dpi: float) -> float:
    return mm * dpi / MM_PER_INCH


def detect_omr(
    warped: Image.Image,
    region: dict[str, Any],
    template_spec: dict[str, Any],
) -> tuple[str | None, float, dict[str, float]]:
    """
    Detect which bubble is filled in an MCQ / True-False answer region.

    Parameters
    ----------
    warped        : Perspective-corrected exam scan (output of detect_and_warp).
    region        : Parsed region_json dict — must contain a ``"bubbles"`` list
                    with entries: ``{label, cx_mm, cy_mm, r_mm}``.
    template_spec : Full template-spec dict (needed for DPI).

    Returns
    -------
    (detected_label, confidence, fill_ratios)
        detected_label : "A" / "B" / "C" / "D" / "True" / "False",
                         or None if no bubble is clearly filled.
        confidence     : 0.0–1.0 — how clearly one bubble stands out from the rest.
                         Below LOW_CONFIDENCE_THRESHOLD the caller should flag the
                         answer for teacher review.
        fill_ratios    : Dict mapping each label → its raw fill ratio (for debug).
    """
    bubbles: list[dict] = region.get("bubbles", [])
    if not bubbles:
        logger.debug("OMR: no bubble positions in region_json — skipping")
        return None, 0.0, {}

    dpi = float(template_spec.get("dpi", 300))

    # Convert to grayscale and binarize
    # THRESH_BINARY_INV: dark (pencil/ink) marks become white (255) in binary
    img_gray = np.array(warped.convert("L"))
    _, binary = cv2.threshold(
        img_gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )

    fill_ratios: dict[str, float] = {}

    for bubble in bubbles:
        label  = bubble["label"]
        cx_px  = int(_mm_to_px(bubble["cx_mm"], dpi))
        cy_px  = int(_mm_to_px(bubble["cy_mm"], dpi))
        r_px   = max(2, int(_mm_to_px(bubble["r_mm"], dpi)))

        h, w = binary.shape
        if cx_px < 0 or cy_px < 0 or cx_px >= w or cy_px >= h:
            logger.warning("OMR: bubble %s centre (%d,%d) out of image bounds", label, cx_px, cy_px)
            fill_ratios[label] = 0.0
            continue

        # Circular mask centred on bubble
        mask = np.zeros(binary.shape, dtype=np.uint8)
        cv2.circle(mask, (cx_px, cy_px), r_px, 255, thickness=-1)

        total_px  = int(mask.sum()) // 255
        if total_px == 0:
            fill_ratios[label] = 0.0
            continue

        filled_px = int(cv2.bitwise_and(binary, binary, mask=mask).sum()) // 255
        fill_ratios[label] = filled_px / total_px

    logger.debug("OMR fill ratios: %s", fill_ratios)

    if not fill_ratios:
        return None, 0.0, fill_ratios

    sorted_labels = sorted(fill_ratios, key=lambda l: fill_ratios[l], reverse=True)
    best   = sorted_labels[0]
    second = sorted_labels[1] if len(sorted_labels) > 1 else None

    best_ratio   = fill_ratios[best]
    second_ratio = fill_ratios[second] if second else 0.0

    # No bubble filled above minimum threshold → no answer detected
    if best_ratio < MIN_FILL_RATIO:
        logger.info(
            "OMR: best fill %.2f below MIN_FILL_RATIO %.2f — no answer detected",
            best_ratio, MIN_FILL_RATIO,
        )
        return None, 0.0, fill_ratios

    # Confidence: relative gap between best and runner-up
    confidence = (best_ratio - second_ratio) / max(best_ratio, 1e-9)

    logger.info(
        "OMR: detected=%s fill=%.2f conf=%.2f (runner-up %s=%.2f)",
        best, best_ratio, confidence, second, second_ratio,
    )

    return best, float(min(confidence, 1.0)), fill_ratios
