"""
pdf_generator.py — Phase 4: Printable exam paper generator.

Generates A4 PDFs containing:
  - 3 ArUco markers (DICT_4X4_50) at TL / BL / BR corners for Phase 5
    perspective correction.
  - 1 QR code at TR corner encoding exam identity (+ student ID when
    generating personalised papers).
  - Question prompts with ruled answer boxes.
  - A template-spec dict (all positions in mm) stored in
    Exam.template_spec_json and ExamQuestion.region_json for Phase 5.

Layout (A4, 210 × 297 mm)
─────────────��────────────────────────────────
 [ArUco TL]   Title / Header info   [QR code]
              Name / ID / Date
 ───────────────��─────────────────────────────  ← y = 55 mm
 Q1. prompt
 ┌─────────────────────────────────────────────┐
 │  (ruled lines)                              │
 └───────────────────────���─────────────────────┘
 Q2. prompt
 ┌──────────────��────────────────────���─────────┐
 │  (ruled lines)                              │
 └────────��─────────────────────────��──────────┘
 [ArUco BL]                         [ArUco BR]
─────────────────────────���────────────────────
"""
from __future__ import annotations

import io
import json
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
import qrcode
import qrcode.constants
from fpdf import FPDF
from PIL import Image

# ── Page layout constants (mm) ─────────────────────────��─────────────────────
PAGE_W: float = 210.0
PAGE_H: float = 297.0
MARGIN: float = 15.0          # left / right content margin
CORNER_OFFSET: float = 10.0   # distance from page edge to marker corner

ARUCO_SIZE: float = 15.0      # ArUco marker square size
QR_SIZE: float = 25.0         # QR code square size

# ArUco marker positions (x, y) = top-left corner of the marker square
_ARUCO_POS: dict[str, tuple[float, float]] = {
    "tl": (CORNER_OFFSET, CORNER_OFFSET),
    "bl": (CORNER_OFFSET, PAGE_H - ARUCO_SIZE - CORNER_OFFSET),
    "br": (PAGE_W - ARUCO_SIZE - CORNER_OFFSET, PAGE_H - ARUCO_SIZE - CORNER_OFFSET),
}
ARUCO_IDS: dict[str, int] = {"tl": 0, "bl": 1, "br": 2}

# QR code: top-right corner
QR_X: float = PAGE_W - QR_SIZE - CORNER_OFFSET
QR_Y: float = CORNER_OFFSET

HEADER_LINE_Y: float = 55.0   # horizontal rule under the header
CONTENT_TOP: float = 58.0     # first question starts here
CONTENT_BOTTOM: float = 268.0 # questions must end above the bottom ArUco row

# ArUco dictionary — 4×4 grid, 50 unique IDs
_ARUCO_DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)


# ── Image helpers ───────────────────────────���─────────────────────────────────

def _aruco_pil(marker_id: int, size_px: int = 150) -> Image.Image:
    """Generate an ArUco marker as a grayscale PIL image."""
    arr = cv2.aruco.generateImageMarker(_ARUCO_DICT, marker_id, size_px)
    return Image.fromarray(arr).convert("RGB")


def _qr_pil(payload: dict[str, Any], size_px: int = 200) -> Image.Image:
    """Generate a QR code from a JSON-serialisable dict."""
    qr = qrcode.QRCode(
        box_size=10,
        border=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
    )
    qr.add_data(json.dumps(payload, separators=(",", ":")))
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return img.resize((size_px, size_px), Image.LANCZOS)


def _embed(pdf: FPDF, img: Image.Image, x: float, y: float, w: float, h: float) -> None:
    """Write a PIL image into the PDF at (x, y) with dimensions (w × h) mm."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    pdf.image(buf, x=x, y=y, w=w, h=h)


def _safe(text: str) -> str:
    """Strip characters outside Latin-1 so FPDF built-in fonts don't crash."""
    return text.encode("latin-1", errors="replace").decode("latin-1")


# ── Public dataclass ──────────────────────────────���───────────────────────────

@dataclass
class QuestionInput:
    id: int
    order_index: int
    prompt: str
    question_type: str = "essay"   # "essay" | "mcq" | "tf" | "identification"
    choices_json: str | None = None  # JSON list of strings for MCQ


# ── Generator ──────────────────────────────────────────────────────────────���──

def generate_exam_paper(
    exam_id: int,
    exam_code: str,
    exam_title: str,
    class_code: str,
    questions: list[QuestionInput],
    student_id: str | None = None,
    student_name: str | None = None,
) -> tuple[bytes, dict]:
    """
    Render a printable A4 exam paper as PDF bytes.

    Parameters
    ----------
    exam_id, exam_code, exam_title, class_code
        Metadata printed in the header.
    questions
        Ordered list of QuestionInput dataclasses.
    student_id, student_name
        When provided the QR payload includes the student ID and the header
        shows the student's name/ID (personalised copy).
        When omitted blank fill-in lines are printed (template copy).

    Returns
    -------
    (pdf_bytes, template_spec)
        template_spec is a dict with all marker and answer-region positions
        in mm — store it in Exam.template_spec_json.
        Each question entry's bounding box should be stored in
        ExamQuestion.region_json.
    """
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(left=MARGIN, top=MARGIN, right=MARGIN)
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    # ── Corner markers ──────────────────────────────────────────────────��─────
    for corner, (mx, my) in _ARUCO_POS.items():
        _embed(pdf, _aruco_pil(ARUCO_IDS[corner]), mx, my, ARUCO_SIZE, ARUCO_SIZE)

    # ── QR code (top-right) ───────────────────────────────────────────────────
    qr_payload: dict[str, Any] = {"exam_id": exam_id}
    if student_id:
        qr_payload["student_id"] = student_id
    _embed(pdf, _qr_pil(qr_payload), QR_X, QR_Y, QR_SIZE, QR_SIZE)

    # ── Header text ───────────────────────────��───────────────────────────────
    # Title — centred between the TL ArUco and the QR code
    title_x = CORNER_OFFSET + ARUCO_SIZE + 3.0
    title_w = QR_X - title_x - 2.0

    pdf.set_font("helvetica", "B", 13)
    pdf.set_xy(title_x, CORNER_OFFSET + 1.0)
    pdf.cell(title_w, 8, _safe(exam_title[:60]), align="C")

    # Row 2 & 3: stay within the horizontal band [title_x … QR_X] to avoid
    # overlapping the TL ArUco marker (x 10–25 mm) and the QR code (x 175–200 mm).
    half_w = title_w / 2.0

    # Class code / exam code row
    pdf.set_font("helvetica", "", 9)
    pdf.set_xy(title_x, CORNER_OFFSET + 12.0)
    pdf.cell(half_w, 5, _safe(f"Class: {class_code}"), align="L")
    pdf.cell(half_w, 5, _safe(f"Exam: {exam_code}"), align="R")

    # Name / student-ID row (still within QR code height; stays left of QR)
    pdf.set_xy(title_x, CORNER_OFFSET + 20.0)
    if student_name and student_id:
        pdf.cell(title_w * 0.6, 5, _safe(f"Name: {student_name}"), align="L")
        pdf.cell(title_w * 0.4, 5, _safe(f"ID: {student_id}"), align="R")
    else:
        pdf.cell(title_w * 0.6, 5, "Name: ____________________________", align="L")
        pdf.cell(title_w * 0.4, 5, "Student ID: __________", align="R")

    # Date / score row
    pdf.set_xy(MARGIN, CORNER_OFFSET + 28.0)
    pdf.cell(180, 5, "Date: __________________    Score: _______ / _______", align="L")

    # Divider
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.4)
    pdf.line(MARGIN, HEADER_LINE_Y, PAGE_W - MARGIN, HEADER_LINE_Y)

    # ── Questions ──────────────────────────────────────────────────────────────
    available_h   = CONTENT_BOTTOM - CONTENT_TOP
    prompt_budget = 10.0   # estimated mm per question prompt (one wrapped line)
    gap           = 3.0    # mm between questions

    # Fixed answer-box heights for non-essay types
    _FIXED_BOX_H: dict[str, float] = {"tf": 12.0, "identification": 12.0}

    fixed_consumed = 0.0
    n_essay = 0
    for _q in questions:
        _qtype = (_q.question_type or "essay").strip()
        if _qtype == "essay":
            n_essay += 1
        elif _qtype == "mcq":
            _choices: list[str] = []
            try:
                _choices = json.loads(_q.choices_json) if _q.choices_json else []
            except Exception:
                _choices = []
            _rows = max(1, (len(_choices) + 3) // 4)
            fixed_consumed += prompt_budget + 10.0 * _rows + 4.0 + gap
        else:
            fixed_consumed += prompt_budget + _FIXED_BOX_H.get(_qtype, 12.0) + gap

    n_essay = max(n_essay, 1)
    essay_remaining = available_h - fixed_consumed - n_essay * (prompt_budget + gap)
    essay_h = max(30.0, essay_remaining / n_essay)

    current_y = CONTENT_TOP
    question_specs: list[dict] = []

    for q in sorted(questions, key=lambda x: x.order_index):
        qtype = q.question_type or "essay"

        # ── Prompt ─────────────────────────────────────────────────────────────
        pdf.set_font("helvetica", "B", 10)
        pdf.set_xy(MARGIN, current_y)
        prompt_text = _safe(f"Q{q.order_index}. {q.prompt[:500]}")
        pdf.multi_cell(PAGE_W - 2 * MARGIN, 5, prompt_text, align="L")
        box_y = pdf.get_y() + 1.0

        box_x = MARGIN
        box_w = PAGE_W - 2 * MARGIN

        # Bubble positions collected per-question for OMR detection (Phase 13)
        bubble_positions: list[dict] = []

        if qtype == "essay":
            # ── Ruled answer box ───────────────────────────────────────────────
            box_h = essay_h
            pdf.set_draw_color(80, 80, 80)
            pdf.set_line_width(0.3)
            pdf.rect(box_x, box_y, box_w, box_h)
            pdf.set_draw_color(190, 190, 190)
            pdf.set_line_width(0.1)
            ly = box_y + 7.0
            while ly < box_y + box_h - 2.0:
                pdf.line(box_x + 2.0, ly, box_x + box_w - 2.0, ly)
                ly += 7.0

        elif qtype == "mcq":
            # ── Letter bubbles (A / B / C / D) ────────────────────────────────
            choices: list[str] = []
            if q.choices_json:
                try:
                    choices = json.loads(q.choices_json)
                except Exception:
                    choices = []
            labels = ["A", "B", "C", "D"]
            bubble_r = 3.5    # radius mm
            col_w = box_w / max(len(choices), 1) if choices else box_w / 4
            row_h = 10.0
            box_h = row_h * max(1, (len(choices) + 3) // 4) + 4.0

            pdf.set_draw_color(60, 60, 60)
            pdf.set_line_width(0.4)
            pdf.set_font("helvetica", "", 9)
            for i, (label, text) in enumerate(zip(labels, choices)):
                cx = box_x + i * col_w + bubble_r + 3.0
                cy = box_y + bubble_r + 3.0
                # circle: fpdf2 uses ellipse
                pdf.ellipse(cx - bubble_r, cy - bubble_r, bubble_r * 2, bubble_r * 2, style="D")
                pdf.set_xy(cx - bubble_r, cy - bubble_r)
                pdf.cell(bubble_r * 2, bubble_r * 2, label, align="C")
                pdf.set_xy(cx + bubble_r + 2.0, cy - 3.5)
                pdf.cell(col_w - bubble_r * 2 - 6.0, 7, _safe(text[:40]), align="L")
                bubble_positions.append({
                    "label": label,
                    "cx_mm": round(cx, 3),
                    "cy_mm": round(cy, 3),
                    "r_mm":  bubble_r,
                })

        elif qtype == "tf":
            # ── True / False bubbles ───────────────────────────────────────────
            bubble_r = 3.5
            box_h = 12.0
            labels_tf = ["True", "False"]
            col_w_tf = 45.0
            pdf.set_draw_color(60, 60, 60)
            pdf.set_line_width(0.4)
            pdf.set_font("helvetica", "", 9)
            for i, label in enumerate(labels_tf):
                cx = box_x + i * col_w_tf + bubble_r + 3.0
                cy = box_y + bubble_r + 3.0
                pdf.ellipse(cx - bubble_r, cy - bubble_r, bubble_r * 2, bubble_r * 2, style="D")
                pdf.set_xy(cx + bubble_r + 2.0, cy - 3.5)
                pdf.cell(col_w_tf - bubble_r * 2 - 6.0, 7, label, align="L")
                bubble_positions.append({
                    "label": label,
                    "cx_mm": round(cx, 3),
                    "cy_mm": round(cy, 3),
                    "r_mm":  bubble_r,
                })

        elif qtype == "identification":
            # ── Short single-line answer box ───────────────────────────────────
            box_h = 12.0
            pdf.set_draw_color(80, 80, 80)
            pdf.set_line_width(0.3)
            pdf.rect(box_x, box_y, box_w, box_h)
        else:
            # Fallback: essay style
            box_h = essay_h
            pdf.set_draw_color(80, 80, 80)
            pdf.set_line_width(0.3)
            pdf.rect(box_x, box_y, box_w, box_h)

        question_specs.append({
            "question_id": q.id,
            "order_index": q.order_index,
            "question_type": qtype,
            "page": 1,
            "x1_mm": round(box_x, 2),
            "y1_mm": round(box_y, 2),
            "x2_mm": round(box_x + box_w, 2),
            "y2_mm": round(box_y + box_h, 2),
            # OMR — bubble centre positions (mm) stored for Phase 13 detection
            "bubbles": bubble_positions,
        })

        current_y = box_y + box_h + gap

    # ── Template spec ─────────────────────────────────────────────────────────
    template_spec: dict[str, Any] = {
        "dpi": 300,
        "page_width_mm": PAGE_W,
        "page_height_mm": PAGE_H,
        "aruco_dict": "DICT_4X4_50",
        "aruco_markers": [
            {
                "id": ARUCO_IDS[corner],
                "corner": corner,
                "x_mm": round(x, 2),
                "y_mm": round(y, 2),
                "size_mm": ARUCO_SIZE,
            }
            for corner, (x, y) in _ARUCO_POS.items()
        ],
        "qr_code": {
            "x_mm": round(QR_X, 2),
            "y_mm": round(QR_Y, 2),
            "size_mm": QR_SIZE,
        },
        "questions": question_specs,
    }

    return bytes(pdf.output()), template_spec
