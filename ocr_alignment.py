"""
ocr_alignment.py — Phase 5/8: Scan alignment, preprocessing, and per-question region cropping.

Full pipeline for each uploaded scan:
  1. preprocess_scan()  — denoise, deskew, contrast-enhance the raw image.
  2. detect_and_warp()  — detect ArUco markers, compute RANSAC homography, warp to template space.
  3. crop_region()      — crop each answer box using region_json (mm → pixels).
  4. preprocess_crop()  — sharpen and enhance contrast on each cropped region before OCR.

If fewer than 2 markers are detected, detect_and_warp() returns (preprocessed_image, False)
and the caller should fall back to full-page OCR on the content area only.
"""
from __future__ import annotations

import logging
from typing import Any

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# Must match the dictionary used in pdf_generator.py
_ARUCO_DICT   = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
_ARUCO_PARAMS = cv2.aruco.DetectorParameters()
_DETECTOR     = cv2.aruco.ArucoDetector(_ARUCO_DICT, _ARUCO_PARAMS)

MM_PER_INCH: float = 25.4


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mm_to_px(mm: float, dpi: float) -> float:
    return mm * dpi / MM_PER_INCH


def _template_marker_corners(template_spec: dict[str, Any]) -> dict[int, np.ndarray]:
    """
    Return the expected pixel corners of each ArUco marker in template space.
    OpenCV aruco corner order: TL → TR → BR → BL.
    Returns {marker_id: ndarray shape (4, 2), dtype float32}.
    """
    dpi = float(template_spec.get("dpi", 300))
    out: dict[int, np.ndarray] = {}
    for m in template_spec["aruco_markers"]:
        x = _mm_to_px(m["x_mm"],    dpi)
        y = _mm_to_px(m["y_mm"],    dpi)
        s = _mm_to_px(m["size_mm"], dpi)
        out[m["id"]] = np.array(
            [[x,     y    ],
             [x + s, y    ],
             [x + s, y + s],
             [x,     y + s]], dtype=np.float32
        )
    return out


# ── Preprocessing — scan level (before ArUco detection) ──────────────────────

def _denoise(rgb: np.ndarray) -> np.ndarray:
    """
    Non-local means denoising (coloured).
    Reduces sensor noise and JPEG compression artifacts.
    h=10 is conservative — strong enough to help ArUco without blurring marker edges.
    """
    return cv2.fastNlMeansDenoisingColored(rgb, None,
                                           h=10, hColor=10,
                                           templateWindowSize=7,
                                           searchWindowSize=21)


def _deskew(rgb: np.ndarray) -> np.ndarray:
    """
    Detect dominant line angle via Hough transform and rotate to correct skew.
    Skips correction if the detected angle is under 0.5° (negligible) or over
    15° (likely wrong detection — don't overcorrect).
    """
    gray  = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=120)

    if lines is None:
        return rgb

    angles: list[float] = []
    for rho, theta in lines[:, 0]:
        angle = (theta - np.pi / 2) * 180.0 / np.pi
        if abs(angle) < 45:
            angles.append(angle)

    if not angles:
        return rgb

    median_angle = float(np.median(angles))
    if abs(median_angle) < 0.5 or abs(median_angle) > 15:
        return rgb

    logger.info("Deskew: rotating by %.2f°", -median_angle)
    h, w   = rgb.shape[:2]
    center = (w // 2, h // 2)
    M      = cv2.getRotationMatrix2D(center, median_angle, 1.0)
    return cv2.warpAffine(rgb, M, (w, h),
                          flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT,
                          borderValue=(255, 255, 255))


def _enhance_contrast(rgb: np.ndarray) -> np.ndarray:
    """
    CLAHE (Contrast Limited Adaptive Histogram Equalisation) on the L channel.
    Improves legibility of faint pencil writing and low-contrast photos.
    """
    lab        = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    l, a, b    = cv2.split(lab)
    clahe      = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_enhanced = clahe.apply(l)
    lab_merged = cv2.merge([l_enhanced, a, b])
    return cv2.cvtColor(lab_merged, cv2.COLOR_LAB2RGB)


def preprocess_scan(scan: Image.Image) -> Image.Image:
    """
    Full preprocessing pipeline applied to the raw uploaded scan before
    ArUco detection and perspective correction.

    Steps: denoise → deskew → contrast enhancement.

    Returns a PIL Image (RGB).
    """
    rgb = np.array(scan.convert("RGB"))
    rgb = _denoise(rgb)
    rgb = _deskew(rgb)
    rgb = _enhance_contrast(rgb)
    return Image.fromarray(rgb)


# ── Preprocessing — crop level (before OCR) ───────────────────────────────────

def _sharpen(rgb: np.ndarray) -> np.ndarray:
    """
    Unsharp mask: enhances edge definition in handwriting strokes.
    Helps Surya detect line boundaries more accurately.
    """
    blurred = cv2.GaussianBlur(rgb, (0, 0), sigmaX=3)
    return cv2.addWeighted(rgb, 1.5, blurred, -0.5, 0)


def preprocess_crop(crop: Image.Image) -> Image.Image:
    """
    Preprocessing applied to each answer-region crop before Surya/Qwen.

    Steps: contrast enhancement → sharpen.

    Keeps the image in RGB (colour) so Qwen2.5-VL receives full colour
    information — binarisation is intentionally avoided as it can hurt VLM
    performance on ambiguous strokes.
    """
    rgb = np.array(crop.convert("RGB"))
    rgb = _enhance_contrast(rgb)
    rgb = _sharpen(rgb)
    return Image.fromarray(rgb)


# ── Alignment ─────────────────────────────────────────────────────────────────

def detect_and_warp(
    scan: Image.Image,
    template_spec: dict[str, Any],
) -> tuple[Image.Image, bool]:
    """
    Detect ArUco markers on *scan* and warp it to template coordinate space.
    Preprocessing (denoise / deskew / CLAHE) is applied automatically before
    marker detection to improve reliability on phone photos.

    Parameters
    ----------
    scan          : Raw uploaded scan (any resolution / orientation).
    template_spec : Parsed Exam.template_spec_json dict.

    Returns
    -------
    (warped_image, success)
        success=False → fewer than 2 matched markers; caller should fall back.
        success=True  → warped PIL Image in template pixel space at template DPI.
    """
    dpi   = float(template_spec.get("dpi", 300))
    out_w = int(_mm_to_px(template_spec["page_width_mm"],  dpi))
    out_h = int(_mm_to_px(template_spec["page_height_mm"], dpi))

    # Preprocess before detection
    preprocessed = preprocess_scan(scan)
    scan_rgb     = np.array(preprocessed)
    gray         = cv2.cvtColor(scan_rgb, cv2.COLOR_RGB2GRAY)

    corners_list, ids, _ = _DETECTOR.detectMarkers(gray)

    n_found = 0 if ids is None else len(ids)
    if n_found < 2:
        logger.warning(
            "ArUco: only %d marker(s) detected — falling back to full-page OCR", n_found
        )
        return preprocessed, False   # return preprocessed even on fallback

    template_corners = _template_marker_corners(template_spec)
    ids_flat = ids.flatten().tolist()

    src_pts: list[np.ndarray] = []
    dst_pts: list[np.ndarray] = []

    for i, mid in enumerate(ids_flat):
        if mid in template_corners:
            src_pts.append(corners_list[i][0])
            dst_pts.append(template_corners[mid])

    matched = len(src_pts)
    if matched < 2:
        logger.warning("ArUco: %d matched marker(s) — need ≥2", matched)
        return preprocessed, False

    src_all = np.concatenate(src_pts, axis=0)
    dst_all = np.concatenate(dst_pts, axis=0)

    H, mask = cv2.findHomography(src_all, dst_all, cv2.RANSAC, ransacReprojThreshold=5.0)
    if H is None:
        logger.warning("ArUco: findHomography returned None")
        return preprocessed, False

    inliers = int(mask.sum()) if mask is not None else "?"
    logger.info(
        "ArUco: homography from %d marker(s), %s/%d inliers",
        matched, inliers, len(src_all),
    )

    warped_np = cv2.warpPerspective(
        scan_rgb, H, (out_w, out_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )
    return Image.fromarray(warped_np), True


def crop_region(
    warped: Image.Image,
    region: dict[str, Any],
    template_spec: dict[str, Any],
    padding_mm: float = 3.0,
) -> Image.Image:
    """
    Crop a single answer region from a perspective-corrected image,
    then apply crop-level preprocessing (CLAHE + sharpen) before returning.

    Parameters
    ----------
    warped        : Output of detect_and_warp() with success=True.
    region        : Dict with x1_mm, y1_mm, x2_mm, y2_mm (from region_json).
    template_spec : Full template spec dict (needed for dpi).
    padding_mm    : Extra margin on every side before cropping.
    """
    dpi = float(template_spec.get("dpi", 300))
    x1  = max(0,             int(_mm_to_px(region["x1_mm"] - padding_mm, dpi)))
    y1  = max(0,             int(_mm_to_px(region["y1_mm"] - padding_mm, dpi)))
    x2  = min(warped.width,  int(_mm_to_px(region["x2_mm"] + padding_mm, dpi)))
    y2  = min(warped.height, int(_mm_to_px(region["y2_mm"] + padding_mm, dpi)))
    raw_crop = warped.crop((x1, y1, x2, y2))
    return preprocess_crop(raw_crop)


def crop_content_area(
    scan: Image.Image,
    template_spec: dict[str, Any],
) -> Image.Image:
    """
    Fallback crop: when ArUco alignment fails, crop the scan to the content
    area below the header line to exclude question prompts and header text.

    Uses HEADER_LINE_Y from the template spec (default 55mm) as the top boundary.
    Returns the preprocessed content area as a PIL Image.
    """
    dpi          = float(template_spec.get("dpi", 300)) if template_spec else 300
    header_y_mm  = 55.0   # matches HEADER_LINE_Y in pdf_generator.py
    content_b_mm = 268.0  # matches CONTENT_BOTTOM in pdf_generator.py

    img_w, img_h = scan.size
    y1 = int(_mm_to_px(header_y_mm,  dpi))
    y2 = int(_mm_to_px(content_b_mm, dpi))

    # Scale y coords to actual image height if image isn't at template DPI
    scale = img_h / _mm_to_px(297.0, dpi)   # 297mm = A4 height
    y1    = int(y1 * scale)
    y2    = min(img_h, int(y2 * scale))

    cropped = scan.crop((0, y1, img_w, y2))
    return preprocess_crop(cropped)
