"""
pdf_generator.py — Phase 4 / 22: Printable exam paper generator.

Generates A4 PDFs containing:
  - 3 ArUco markers (DICT_4X4_50) at TL / BL / BR corners for Phase 5
    perspective correction.
  - 1 QR code at TR corner encoding exam identity (+ student ID when
    generating personalised papers).
  - Compact answer regions WITHOUT question prompts or choice text:
      MCQ         → numbered row of A/B/C/D bubbles only
      True/False  → numbered row of T/F bubbles only
      Identification → numbered single-line answer box
      Essay       → numbered ruled answer box
  - When objective questions > 10, MCQ / TF / Identification are laid out
    in TWO columns to maximise space.
  - A template-spec dict (all positions in mm) stored in
    Exam.template_spec_json and ExamQuestion.region_json for Phase 5.

Layout (A4, 210 × 297 mm)
──────────────────────────────────────────────────────────────────────
 [ArUco TL]   Title / Header info   [QR code]
              Name / ID / Date
 ──────────────────────────────────────────────────────────────────  y = 55 mm
 Objective section  (1 or 2 columns)
   Q1.  ○A  ○B  ○C  ○D          Q11.  ○A  ○B  ○C  ○D
   Q2.  ○T  ○F                  Q12.  [________________]
   ...                          ...
 ──────────────────────────────────────────────────────────────────
 Essay section  (always single column)
   Q9.
   ┌─────────────────────────────────────────────────────────────┐
   │  (ruled lines)                                              │
   └─────────────────────────────────────────────────────────────┘
 [ArUco BL]                                          [ArUco BR]
──────────────────────────────────────────────────────────────────
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

# ── Page layout constants (mm) ────────────────────────────────────────────────
PAGE_W: float = 210.0
PAGE_H: float = 297.0
MARGIN: float = 15.0
CORNER_OFFSET: float = 10.0

ARUCO_SIZE: float = 15.0
QR_SIZE: float = 25.0

_ARUCO_POS: dict[str, tuple[float, float]] = {
    "tl": (CORNER_OFFSET, CORNER_OFFSET),
    "bl": (CORNER_OFFSET, PAGE_H - ARUCO_SIZE - CORNER_OFFSET),
    "br": (PAGE_W - ARUCO_SIZE - CORNER_OFFSET, PAGE_H - ARUCO_SIZE - CORNER_OFFSET),
}
ARUCO_IDS: dict[str, int] = {"tl": 0, "bl": 1, "br": 2}

QR_X: float = PAGE_W - QR_SIZE - CORNER_OFFSET
QR_Y: float = CORNER_OFFSET

HEADER_LINE_Y: float = 55.0
CONTENT_TOP: float   = 58.0
CONTENT_BOTTOM: float = 268.0

# ── Compact objective layout constants ────────────────────────────────────────
BUBBLE_R: float      = 3.0    # mm radius (slightly larger than 2.8 for OMR reliability)
BUBBLE_SPACING: float = 7.5   # mm centre-to-centre between adjacent bubbles
Q_LABEL_W: float     = 12.0   # mm reserved for "Q10." label

OBJ_ROW_H: float     = 8.5    # mm total height per objective question row
OBJ_GAP: float       = 1.5    # mm gap between objective rows

ID_BOX_H: float      = 14.0   # mm height of identification answer box (taller = more pixels for Qwen)
ESSAY_GAP: float     = 3.0    # mm gap between essay questions

TWO_COL_THRESHOLD: int = 10   # use two columns when # objective Qs > this
COL_GAP: float        = 6.0   # mm gap between columns

_ARUCO_DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)


# ── Image helpers ─────────────────────────────────────────────────────────────

def _aruco_pil(marker_id: int, size_px: int = 150) -> Image.Image:
    arr = cv2.aruco.generateImageMarker(_ARUCO_DICT, marker_id, size_px)
    return Image.fromarray(arr).convert("RGB")


def _qr_pil(payload: dict[str, Any], size_px: int = 200) -> Image.Image:
    qr = qrcode.QRCode(box_size=10, border=1,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(json.dumps(payload, separators=(",", ":")))
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return img.resize((size_px, size_px), Image.LANCZOS)


def _embed(pdf: FPDF, img: Image.Image, x: float, y: float, w: float, h: float) -> None:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    pdf.image(buf, x=x, y=y, w=w, h=h)


def _safe(text: str) -> str:
    return text.encode("latin-1", errors="replace").decode("latin-1")


# ── Public dataclass ──────────────────────────────────────────────────────────

@dataclass
class QuestionInput:
    id: int
    order_index: int
    prompt: str
    question_type: str = "essay"
    choices_json: str | None = None


# ── Question-height helpers ───────────────────────────────────────────────────

def _obj_row_h(qtype: str) -> float:
    """Vertical space consumed by one objective question (no prompt)."""
    if qtype == "identification":
        return ID_BOX_H + 3.0   # small box + top spacing for Q-label
    return OBJ_ROW_H


def _section_height(qs: list[QuestionInput], two_col: bool) -> float:
    """Total vertical mm consumed by the objective section."""
    if not qs:
        return 0.0
    heights = [_obj_row_h(q.question_type or "essay") + OBJ_GAP for q in qs]
    if two_col:
        mid    = (len(qs) + 1) // 2
        left_h  = sum(heights[:mid])
        right_h = sum(heights[mid:])
        return max(left_h, right_h)
    return sum(heights)


# ── Objective question rendering ──────────────────────────────────────────────

def _render_mcq(
    pdf: FPDF, q: QuestionInput,
    col_x: float, col_y: float, col_w: float,
) -> dict:
    """Draw a compact MCQ row (question number + A/B/C/D bubbles, no text)."""
    choices: list[str] = []
    if q.choices_json:
        try:
            choices = json.loads(q.choices_json)
        except Exception:
            choices = []
    labels = ["A", "B", "C", "D"][: len(choices)] if choices else ["A", "B", "C", "D"]

    row_h = OBJ_ROW_H
    cy    = col_y + row_h / 2.0   # vertical centre of the row

    # Question number label
    pdf.set_font("helvetica", "B", 8)
    pdf.set_xy(col_x, cy - 2.5)
    pdf.cell(Q_LABEL_W, 5, f"Q{q.order_index}.", align="L")

    # Bubbles
    pdf.set_draw_color(60, 60, 60)
    pdf.set_line_width(0.4)
    pdf.set_font("helvetica", "", 7)

    bubble_positions: list[dict] = []
    for i, label in enumerate(labels):
        cx = col_x + Q_LABEL_W + i * BUBBLE_SPACING + BUBBLE_R
        pdf.ellipse(cx - BUBBLE_R, cy - BUBBLE_R, BUBBLE_R * 2, BUBBLE_R * 2, style="D")
        # Letter centred inside bubble
        pdf.set_xy(cx - BUBBLE_R, cy - BUBBLE_R)
        pdf.cell(BUBBLE_R * 2, BUBBLE_R * 2, label, align="C")
        bubble_positions.append({
            "label": label,
            "cx_mm": round(cx, 3),
            "cy_mm": round(cy, 3),
            "r_mm":  BUBBLE_R,
        })

    return {
        "question_id":   q.id,
        "order_index":   q.order_index,
        "question_type": "mcq",
        "page": 1,
        "x1_mm": round(col_x + Q_LABEL_W, 2),
        "y1_mm": round(col_y, 2),
        "x2_mm": round(col_x + col_w, 2),
        "y2_mm": round(col_y + row_h, 2),
        "bubbles": bubble_positions,
    }


def _render_tf(
    pdf: FPDF, q: QuestionInput,
    col_x: float, col_y: float, col_w: float,
) -> dict:
    """Draw a compact T/F row (question number + T/F bubbles, no text)."""
    row_h = OBJ_ROW_H
    cy    = col_y + row_h / 2.0

    pdf.set_font("helvetica", "B", 8)
    pdf.set_xy(col_x, cy - 2.5)
    pdf.cell(Q_LABEL_W, 5, f"Q{q.order_index}.", align="L")

    pdf.set_draw_color(60, 60, 60)
    pdf.set_line_width(0.4)
    pdf.set_font("helvetica", "", 7)

    # T and F with wider spacing so teacher can distinguish at a glance
    labels_display = [("T", "True"), ("F", "False")]
    bubble_positions: list[dict] = []
    for i, (display, full_label) in enumerate(labels_display):
        cx = col_x + Q_LABEL_W + i * (BUBBLE_SPACING + 1.5) + BUBBLE_R
        pdf.ellipse(cx - BUBBLE_R, cy - BUBBLE_R, BUBBLE_R * 2, BUBBLE_R * 2, style="D")
        pdf.set_xy(cx - BUBBLE_R, cy - BUBBLE_R)
        pdf.cell(BUBBLE_R * 2, BUBBLE_R * 2, display, align="C")
        bubble_positions.append({
            "label": full_label,      # "True" / "False" for OMR matching
            "cx_mm": round(cx, 3),
            "cy_mm": round(cy, 3),
            "r_mm":  BUBBLE_R,
        })

    return {
        "question_id":   q.id,
        "order_index":   q.order_index,
        "question_type": "tf",
        "page": 1,
        "x1_mm": round(col_x + Q_LABEL_W, 2),
        "y1_mm": round(col_y, 2),
        "x2_mm": round(col_x + col_w, 2),
        "y2_mm": round(col_y + row_h, 2),
        "bubbles": bubble_positions,
    }


def _render_identification(
    pdf: FPDF, q: QuestionInput,
    col_x: float, col_y: float, col_w: float,
) -> dict:
    """Draw a compact identification row (question number + small answer box)."""
    row_h  = _obj_row_h("identification")
    box_y  = col_y + 1.5
    box_x  = col_x + Q_LABEL_W
    box_w  = col_w - Q_LABEL_W

    pdf.set_font("helvetica", "B", 8)
    pdf.set_xy(col_x, box_y)
    pdf.cell(Q_LABEL_W, ID_BOX_H, f"Q{q.order_index}.", align="L")

    pdf.set_draw_color(80, 80, 80)
    pdf.set_line_width(0.3)
    pdf.rect(box_x, box_y, box_w, ID_BOX_H)

    return {
        "question_id":   q.id,
        "order_index":   q.order_index,
        "question_type": "identification",
        "page": 1,
        "x1_mm": round(box_x, 2),
        "y1_mm": round(box_y, 2),
        "x2_mm": round(box_x + box_w, 2),
        "y2_mm": round(box_y + ID_BOX_H, 2),
        "bubbles": [],
    }


def _render_objective(
    pdf: FPDF, q: QuestionInput,
    col_x: float, col_y: float, col_w: float,
) -> dict:
    """Dispatch to the correct objective renderer."""
    qtype = (q.question_type or "essay").strip()
    if qtype == "mcq":
        return _render_mcq(pdf, q, col_x, col_y, col_w)
    if qtype == "tf":
        return _render_tf(pdf, q, col_x, col_y, col_w)
    return _render_identification(pdf, q, col_x, col_y, col_w)


# ── Essay question rendering ──────────────────────────────────────────────────

def _render_essay(
    pdf: FPDF, q: QuestionInput,
    margin: float, y: float, width: float, essay_h: float,
) -> dict:
    """Draw a question-number label ABOVE the ruled answer box. No prompt text printed."""
    label_h = 5.0
    pdf.set_font("helvetica", "B", 10)
    pdf.set_xy(margin, y)
    pdf.cell(width, label_h, f"Q{q.order_index}.", align="L")
    box_y = y + label_h + 1.0   # label sits fully above the box, 1 mm gap

    # Outer border
    pdf.set_draw_color(80, 80, 80)
    pdf.set_line_width(0.3)
    pdf.rect(margin, box_y, width, essay_h)

    # Ruled lines
    pdf.set_draw_color(190, 190, 190)
    pdf.set_line_width(0.1)
    ly = box_y + 7.0
    while ly < box_y + essay_h - 2.0:
        pdf.line(margin + 2.0, ly, margin + width - 2.0, ly)
        ly += 7.0

    return {
        "question_id":   q.id,
        "order_index":   q.order_index,
        "question_type": "essay",
        "page": 1,
        "x1_mm": round(margin, 2),
        "y1_mm": round(box_y, 2),
        "x2_mm": round(margin + width, 2),
        "y2_mm": round(box_y + essay_h, 2),
        "bubbles": [],
    }


# ── Public generator ──────────────────────────────────────────────────────────

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

    Returns
    -------
    (pdf_bytes, template_spec)
        template_spec has all marker / answer-region positions in mm.
    """
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(left=MARGIN, top=MARGIN, right=MARGIN)
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    # ── Corner markers ────────────────────────────────────────────────────────
    for corner, (mx, my) in _ARUCO_POS.items():
        _embed(pdf, _aruco_pil(ARUCO_IDS[corner]), mx, my, ARUCO_SIZE, ARUCO_SIZE)

    # ── QR code ───────────────────────────────────────────────────────────────
    qr_payload: dict[str, Any] = {"exam_id": exam_id}
    if student_id:
        qr_payload["student_id"] = student_id
    _embed(pdf, _qr_pil(qr_payload), QR_X, QR_Y, QR_SIZE, QR_SIZE)

    # ── Header text ───────────────────────────────────────────────────────────
    title_x = CORNER_OFFSET + ARUCO_SIZE + 3.0
    title_w = QR_X - title_x - 2.0
    half_w  = title_w / 2.0

    pdf.set_font("helvetica", "B", 13)
    pdf.set_xy(title_x, CORNER_OFFSET + 1.0)
    pdf.cell(title_w, 8, _safe(exam_title[:60]), align="C")

    pdf.set_font("helvetica", "", 9)
    pdf.set_xy(title_x, CORNER_OFFSET + 12.0)
    pdf.cell(half_w, 5, _safe(f"Class: {class_code}"), align="L")
    pdf.cell(half_w, 5, _safe(f"Exam: {exam_code}"), align="R")

    pdf.set_xy(title_x, CORNER_OFFSET + 20.0)
    if student_name and student_id:
        pdf.cell(title_w * 0.6, 5, _safe(f"Name: {student_name}"), align="L")
        pdf.cell(title_w * 0.4, 5, _safe(f"ID: {student_id}"), align="R")
    else:
        pdf.cell(title_w * 0.6, 5, "Name: ____________________________", align="L")
        pdf.cell(title_w * 0.4, 5, "Student ID: __________", align="R")

    pdf.set_xy(MARGIN, CORNER_OFFSET + 28.0)
    pdf.cell(180, 5, "Date: __________________    Score: _______ / _______", align="L")

    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.4)
    pdf.line(MARGIN, HEADER_LINE_Y, PAGE_W - MARGIN, HEADER_LINE_Y)

    # ── Partition questions ───────────────────────────────────────────────────
    all_sorted = sorted(questions, key=lambda x: x.order_index)
    obj_qs   = [q for q in all_sorted
                if (q.question_type or "essay").strip() in ("mcq", "tf", "identification")]
    essay_qs = [q for q in all_sorted
                if (q.question_type or "essay").strip() == "essay"]

    use_two_col = len(obj_qs) > TWO_COL_THRESHOLD

    if use_two_col:
        col_w   = (PAGE_W - 2.0 * MARGIN - COL_GAP) / 2.0
        left_x  = MARGIN
        right_x = MARGIN + col_w + COL_GAP
    else:
        col_w   = PAGE_W - 2.0 * MARGIN
        left_x  = MARGIN
        right_x = MARGIN   # unused in single-column

    # ── Space allocation ──────────────────────────────────────────────────────
    available_h   = CONTENT_BOTTOM - CONTENT_TOP
    obj_section_h = _section_height(obj_qs, use_two_col)
    section_sep   = 4.0 if (obj_qs and essay_qs) else 0.0
    essay_avail   = available_h - obj_section_h - section_sep
    n_essay       = max(len(essay_qs), 1)
    # Each essay box: ~6mm for "Q1." line + box + gap
    essay_h       = max(25.0, (essay_avail - n_essay * (6.0 + ESSAY_GAP)) / n_essay)

    # ── Render objective section ──────────────────────────────────────────────
    question_specs: list[dict] = []
    current_y = CONTENT_TOP

    if obj_qs:
        if use_two_col:
            mid      = (len(obj_qs) + 1) // 2
            left_qs  = obj_qs[:mid]
            right_qs = obj_qs[mid:]
            left_y   = current_y
            right_y  = current_y

            for q in left_qs:
                spec = _render_objective(pdf, q, left_x, left_y, col_w)
                question_specs.append(spec)
                left_y += _obj_row_h(q.question_type or "essay") + OBJ_GAP

            for q in right_qs:
                spec = _render_objective(pdf, q, right_x, right_y, col_w)
                question_specs.append(spec)
                right_y += _obj_row_h(q.question_type or "essay") + OBJ_GAP

            current_y = max(left_y, right_y)
        else:
            for q in obj_qs:
                spec = _render_objective(pdf, q, left_x, current_y, col_w)
                question_specs.append(spec)
                current_y += _obj_row_h(q.question_type or "essay") + OBJ_GAP

        if essay_qs:
            # Light divider between sections
            pdf.set_draw_color(180, 180, 180)
            pdf.set_line_width(0.2)
            pdf.line(MARGIN, current_y + 1.0, PAGE_W - MARGIN, current_y + 1.0)
            current_y += section_sep

    # ── Render essay section ──────────────────────────────────────────────────
    width = PAGE_W - 2.0 * MARGIN
    for q in essay_qs:
        spec = _render_essay(pdf, q, MARGIN, current_y, width, essay_h)
        question_specs.append(spec)
        current_y += 6.0 + essay_h + ESSAY_GAP

    # ── Template spec ─────────────────────────────────────────────────────────
    template_spec: dict[str, Any] = {
        "dpi": 300,
        "page_width_mm":  PAGE_W,
        "page_height_mm": PAGE_H,
        "aruco_dict": "DICT_4X4_50",
        "aruco_markers": [
            {
                "id":      ARUCO_IDS[corner],
                "corner":  corner,
                "x_mm":    round(x, 2),
                "y_mm":    round(y, 2),
                "size_mm": ARUCO_SIZE,
            }
            for corner, (x, y) in _ARUCO_POS.items()
        ],
        "qr_code": {
            "x_mm":    round(QR_X, 2),
            "y_mm":    round(QR_Y, 2),
            "size_mm": QR_SIZE,
        },
        "questions": question_specs,
    }

    return bytes(pdf.output()), template_spec
