"""
id_ocr.py — single-line OCR for identification answer boxes.

Runs on the GPU host (the Vast.ai instance via vast_ocr_server.py's /ocr_id
endpoint, or locally when no REMOTE_OCR_URL is set). Deliberately kept apart
from ocr_pipeline.run_ocr_pipeline so essay OCR — and the CER/WER numbers
measured on it — stay byte-for-byte unchanged: this module only *calls into*
ocr_pipeline, never modifies it.

Why identification skips line detection entirely
------------------------------------------------
Surya finds lines of text, and an identification box holds exactly one short
answer floating in a mostly empty rectangle — far less evidence than the long
parallel lines of an essay page. Confirmed failures on real submissions:
a bold "Peace" was split into two thin slivers (top halves of the letters in
one box, bottom edges in another), which Qwen then read as "Beluca" + "c4";
elsewhere the first word of a two-word answer was dropped entirely.

Since the box is single-line by construction, there is nothing for a line
detector to decide: hand the whole crop to Qwen as one line. Same model, same
greedy decoding, same per-line confidence used for review flagging.
"""
from __future__ import annotations

import inspect
import os

from PIL import Image

import ocr_pipeline

# Same threshold the essay path uses for "Qwen wasn't sure about this line"
# (see run_ocr_pipeline) — read here rather than imported so this module
# never depends on ocr_pipeline's private names.
MIN_CONFIDENCE = float(os.getenv("OCR_MIN_LINE_CONFIDENCE", "0.15"))

# One short answer (typically 1-5 words). The essay path's per-line budget is
# 128 tokens for a full-width line of prose, so this is generous headroom
# while still capping generation on an ambiguous crop.
ID_ANSWER_TOKENS = int(os.getenv("ID_OCR_MAX_TOKENS", "128"))


def transcribe_answer_box(crop: Image.Image) -> tuple[str, float]:
    """
    Transcribe one identification answer box.

    Returns (text, confidence), where confidence is Qwen's least-certain
    token probability for the answer — the same measure the essay path
    flags low-confidence lines with.
    """
    assert ocr_pipeline.MODELS is not None, "OCR models not loaded"
    # token_budgets was added to qwen_ocr_lines by the batching work; the GPU
    # host runs a manually uploaded copy of ocr_pipeline.py that may predate
    # it, so fall back to the one-argument form rather than 500-ing there.
    if "token_budgets" in inspect.signature(ocr_pipeline.qwen_ocr_lines).parameters:
        results = ocr_pipeline.qwen_ocr_lines([crop.convert("RGB")], [ID_ANSWER_TOKENS])
    else:
        results = ocr_pipeline.qwen_ocr_lines([crop.convert("RGB")])
    if not results:
        return "", 1.0
    text, confidence = results[0]
    return text.strip(), confidence
