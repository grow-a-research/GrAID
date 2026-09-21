"""
text_normalize.py — turn per-line OCR output into readable prose.

Surya detects one box per physical handwriting line, so run_ocr_pipeline
joins the transcriptions with newlines: a sentence spanning three written
lines arrives as three fragments. Measured on ESSAY-TEST 3, 19 of one
submission's 25 lines ended mid-sentence, while another submission had been
reflowed into paragraphs by the Groq cleanup — so identical writing reached
the grader either as prose or as fragments, and "Organization" and "Writing
Mechanics" were partly scoring our line detection.

Two functions, two purposes:

  join_wrapped_lines()  — for GRADING and display. Rejoins wrapped lines and
                          hyphen-split words, and keeps a break only where the
                          student actually started a new paragraph (detected
                          from each line's left edge, when box positions are
                          available).

  normalize_for_metrics() — for CER/WER. Flattens all line structure on BOTH
                          the reference and the transcription, so a line wrap
                          isn't counted as a transcription error.
"""
from __future__ import annotations

import re

# A line starting this much further right than the body text is an indent —
# i.e. the student began a new paragraph. 5mm at 300dpi ≈ 59px; the value is
# in the same pixel space as the boxes handed in (the answer crop).
_PARAGRAPH_INDENT_PX = 59

# Sentence-ending punctuation; a wrapped line that ends mid-sentence is
# joined to the next one regardless of indentation.
_SENTENCE_END = re.compile(r"[.!?][\"')\]]*\s*$")

# "activi-" at the end of a line, continued on the next.
_HYPHEN_SPLIT = re.compile(r"(\w)[-‐‑]\s*$")


def _is_paragraph_start(box, body_left: float | None) -> bool:
    """True when this line's left edge is indented well past the body text."""
    if box is None or body_left is None:
        return False
    return float(box[0]) > body_left + _PARAGRAPH_INDENT_PX


def join_wrapped_lines(
    text: str,
    boxes: list[tuple[int, int, int, int]] | None = None,
) -> str:
    """
    Rejoin OCR line wraps into sentences and paragraphs.

    `boxes` is the per-line geometry from the OCR pass, in the same order as
    the lines. When it lines up, an indented line starts a new paragraph;
    without it, a break is kept only where the previous line ended a sentence
    AND the text already had a blank line there.
    """
    raw_lines = text.split("\n")
    use_boxes = bool(boxes) and len(boxes) == len(raw_lines)

    lefts = [float(b[0]) for b in boxes] if use_boxes else []
    # The body's left margin: most lines start there, so the median is robust
    # against both indented paragraph openings and stray short detections.
    body_left = sorted(lefts)[len(lefts) // 2] if lefts else None

    paragraphs: list[list[str]] = []
    current: list[str] = []
    for i, line in enumerate(raw_lines):
        stripped = line.strip()
        if not stripped:
            # A blank line is an explicit break (e.g. between merged pages).
            if current:
                paragraphs.append(current)
                current = []
            continue
        box = boxes[i] if use_boxes else None
        starts_paragraph = bool(current) and _is_paragraph_start(box, body_left) and (
            _SENTENCE_END.search(current[-1]) is not None
        )
        if starts_paragraph:
            paragraphs.append(current)
            current = []
        current.append(stripped)
    if current:
        paragraphs.append(current)

    out: list[str] = []
    for para in paragraphs:
        buf = ""
        for line in para:
            if not buf:
                buf = line
                continue
            hyphen = _HYPHEN_SPLIT.search(buf)
            if hyphen:
                # "activi-" + "ties" -> "activities"
                buf = buf[: hyphen.start(1) + 1] + line.lstrip()
            else:
                buf = f"{buf} {line}"
        out.append(buf.strip())
    return "\n\n".join(p for p in out if p)


# A leading line that is the printed "Q<n>." label rather than writing.
_QUESTION_LABEL = re.compile(r"^\s*Q\s*\d+\s*[.:)]?\s*$", re.I)

# How closely a transcribed line must match the question's printed prompt
# before it's treated as the prompt bleeding into the crop. Tolerant enough
# to survive OCR misreads of the printed text, strict enough that a
# student's own sentence on the same topic doesn't match.
_PROMPT_SIMILARITY = 0.6


def strip_printed_prompt(text: str, question_prompt: str | None) -> str:
    """
    Remove the printed question prompt from the start of an answer.

    The crop can catch the tail of the printed prompt or its "Q<n>." label
    sitting above the answer box, and the grader would otherwise read the
    question as part of the student's answer. Only LEADING lines are
    considered, and a line is removed only when it matches the exam's own
    stored prompt — we know exactly what is printed there, so this needs no
    guessing about question-shaped sentences (a student's answer may well
    end in a question mark).
    """
    from difflib import SequenceMatcher

    lines = text.split("\n")
    prompt = " ".join((question_prompt or "").split()).casefold()
    while lines:
        candidate = lines[0].strip()
        if not candidate:
            lines.pop(0)
            continue
        if _QUESTION_LABEL.match(candidate):
            lines.pop(0)
            continue
        if prompt:
            head = candidate.casefold()
            # Compare against the prompt's opening of the same length, so a
            # partially-cropped prompt line still matches.
            ratio = SequenceMatcher(None, prompt[: max(20, len(head))], head).ratio()
            if ratio >= _PROMPT_SIMILARITY:
                lines.pop(0)
                continue
        break
    return "\n".join(lines)


def normalize_for_metrics(text: str | None) -> str:
    """
    Flatten text for CER/WER so line structure isn't scored as error.

    Applied to BOTH the teacher's reference and the OCR output: rejoins
    hyphen-split words, collapses every run of whitespace (including line
    breaks) to a single space, and trims.
    """
    if not text:
        return ""
    joined = re.sub(r"(\w)[-‐‑]\s*\n\s*(\w)", r"\1\2", text)
    return " ".join(joined.split())
