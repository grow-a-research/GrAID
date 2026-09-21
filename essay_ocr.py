"""
essay_ocr.py — two-pass OCR for essay answer crops.

Surya's line detection is unstable on handwriting: on the same crop it may
separate every line, or merge two or three into one tall box that Qwen then
transcribes incompletely. Which way it goes depends on the writing, not on a
measurable property of the image — measured line spacing was 82-86px across
four real essays whose best scale ranged from 0.5x to 1.0x, so there is no
single scale (and nothing to "normalise" to) that works for all of them.

So run the crop at two scales and keep the better result. Measured on four
real submissions (full size vs 0.65x):

    sub 165:  967 ->  1265 unique chars  (recovered a dropped final paragraph)
    sub 166: 1161 ->  1051               (full size kept)
    sub 159:  432 ->   449
    sub 163:  250 ->   253               (CER vs reference 0.040 -> 0.020)

Cost is one extra OCR round-trip per essay; identification answers don't use
this path (they go to the single-line /ocr_id endpoint).
"""
from __future__ import annotations

import logging
from difflib import SequenceMatcher

import cv2
import numpy as np
from PIL import Image

import ocr_pipeline
from text_normalize import join_wrapped_lines

logger = logging.getLogger(__name__)

# A detected line box with less ink than this is blank paper, not writing.
# Measured on a real submission: genuine lines ran 8.8-33% dark pixels, while
# five boxes Surya found on the empty ruled area below the essay measured
# exactly 0.00% — and Qwen, handed a blank crop, invented text for them
# ("The quick brown fox jumps over the lazy dog.", "This is a handwriting
# recognition task, not", 问题解决), which then went to the grader as if the
# student had written it.
_BLANK_BOX_INK_FRACTION = 0.01

# Text Qwen emits when a crop has nothing readable in it. These are the
# model's filler, never a student's answer, and they have arrived both with a
# blank box (caught by the ink check) and with the line/box counts out of
# step, where the ink check can't run — so they're removed by text as well.
_FILLER_LINES = (
    "the quick brown fox jumps over the lazy dog",
    "this is a handwriting recognition task",
    "lorem ipsum",
)


def _is_filler(line: str) -> bool:
    """True for a line that is model filler rather than transcribed writing."""
    stripped = "".join(ch for ch in line.casefold() if ch.isalnum() or ch.isspace()).strip()
    stripped = " ".join(stripped.split())
    if any(stripped.startswith(f) or f in stripped for f in _FILLER_LINES):
        return True
    # A line with no Latin letters at all (e.g. 问题解决) on an English exam.
    letters = [ch for ch in line if ch.isalpha()]
    return bool(letters) and not any(ch.isascii() for ch in letters)

# Full size first, so a tie keeps today's behavior.
ESSAY_OCR_SCALES: tuple[float, ...] = (1.0, 0.65)

# Similarity above which a line is treated as a re-read of the line before it
# (the failure mode overlapping boxes produce), so a pass can't win just by
# transcribing the same line twice.
_DUPLICATE_SIMILARITY = 0.6

# A first line whose box hugs the crop's top edge (within this many pixels)
# and is shorter than this fraction of the median line height is the clipped
# bottom of writing above the answer box, not a line of the answer.
_TOP_EDGE_TOLERANCE_PX = 3
_SLIVER_HEIGHT_RATIO = 0.5


def unique_content_length(text: str) -> int:
    """
    Characters of text left after dropping lines that re-read the previous one.

    Only ADJACENT lines are compared, and by sequence similarity rather than
    shared words. An earlier version compared every line against every kept
    line by word overlap, which discarded genuine lines from an essay that
    reuses phrases — on a real submission it scored the complete
    transcription (1279 chars) below a truncated one (949), and the selector
    then kept the truncated pass. Duplicate reads come from overlapping line
    boxes, so they are always neighbours.
    """
    kept: list[str] = []
    for line in (l for l in text.split("\n") if l.strip()):
        if kept and SequenceMatcher(
            None, kept[-1].casefold(), line.casefold()
        ).ratio() >= _DUPLICATE_SIMILARITY:
            continue
        kept.append(line)
    return sum(len(k) for k in kept)


def _drop_blank_boxes(
    crop: Image.Image,
    text: str,
    boxes: list[tuple[int, int, int, int]],
) -> tuple[str, list[tuple[int, int, int, int]]]:
    """
    Remove transcribed lines whose box contains no ink (see
    _BLANK_BOX_INK_FRACTION). Lines and boxes are positionally paired, so
    this only runs when their counts match; otherwise the text is returned
    untouched rather than risk dropping the wrong line.
    """
    lines = text.split("\n")

    # Model filler is dropped by text first, so it goes even when the line and
    # box counts disagree (the server's duplicate-line removal can drop a line
    # while keeping its box, which is exactly when a hallucinated trailing
    # line used to survive).
    filtered = []
    for line in lines:
        if _is_filler(line):
            logger.info("Essay OCR: dropped model filler line: %r", line[:60])
            continue
        filtered.append(line)
    if len(filtered) != len(lines):
        # Boxes no longer pair with lines; keep the text, skip the ink pass.
        return "\n".join(filtered), boxes
    lines = filtered

    if not boxes or len(lines) != len(boxes):
        return "\n".join(lines), boxes

    gray = cv2.cvtColor(np.asarray(crop.convert("RGB")), cv2.COLOR_RGB2GRAY)
    kept_lines: list[str] = []
    kept_boxes: list[tuple[int, int, int, int]] = []
    for line, box in zip(lines, boxes):
        x1, y1, x2, y2 = (int(v) for v in box)
        patch = gray[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
        if patch.size:
            otsu, _ = cv2.threshold(patch, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            ink = float((patch < max(60, otsu * 0.75)).mean())
            if ink < _BLANK_BOX_INK_FRACTION:
                logger.info("Essay OCR: dropped blank-box line (%.2f%% ink): %r", ink * 100, line[:60])
                continue
        kept_lines.append(line)
        kept_boxes.append(box)
    return "\n".join(kept_lines), kept_boxes


def _drop_top_edge_sliver(
    text: str,
    boxes: list[tuple[int, int, int, int]],
) -> tuple[str, list[tuple[int, int, int, int]]]:
    """
    Drop a first line that is only the clipped bottom of writing ABOVE the box.

    Students sometimes write a title or label above the answer box; the crop
    catches its lower few pixels and Qwen transcribes the fragment as a word
    ("Calming", from a clipped "family feud"). Measured on that submission:
    the sliver's box was 19px tall against a 62px median and sat flush with
    the crop's top edge, while every real line measured 0.95-1.11x median.
    Only the FIRST line is ever considered.
    """
    lines = text.split("\n")
    if len(lines) < 3 or len(lines) != len(boxes):
        return text, boxes
    heights = sorted(b[3] - b[1] for b in boxes)
    median = heights[len(heights) // 2]
    top, first = boxes[0], lines[0]
    if median > 0 and top[1] <= _TOP_EDGE_TOLERANCE_PX and (top[3] - top[1]) < median * _SLIVER_HEIGHT_RATIO:
        logger.info(
            "Essay OCR: dropped top-edge sliver (%dpx vs %dpx median): %r",
            top[3] - top[1], median, first[:40],
        )
        return "\n".join(lines[1:]), boxes[1:]
    return text, boxes


def run_essay_ocr(
    crop: Image.Image,
) -> tuple[str, list[tuple[int, int, int, int]], bool]:
    """
    OCR one essay crop at each scale in ESSAY_OCR_SCALES, returning the pass
    with the most unique content as (text, boxes, low_confidence). Boxes are
    always in the original crop's coordinates.
    """
    best: tuple[int, str, list, bool] | None = None
    for factor in ESSAY_OCR_SCALES:
        if factor == 1.0:
            image = crop
        else:
            image = crop.resize(
                (max(1, int(crop.width * factor)), max(1, int(crop.height * factor))),
                Image.LANCZOS,
            )
        text, boxes, _, low_conf = ocr_pipeline.run_ocr_pipeline(image, include_boxed_image=False)
        if factor != 1.0:
            boxes = [tuple(int(v / factor) for v in box) for box in boxes]
        text, boxes = _drop_blank_boxes(crop, text, boxes)
        text, boxes = _drop_top_edge_sliver(text, boxes)
        score = unique_content_length(text)
        logger.info(
            "Essay OCR pass x%.2f: %d boxes, %d chars (%d unique)",
            factor, len(boxes), len(text), score,
        )
        if best is None or score > best[0]:
            best = (score, text, boxes, low_conf)

    assert best is not None
    _, text, boxes, low_conf = best
    # Hand the grader prose, not one fragment per written line — see
    # text_normalize.join_wrapped_lines for why this matters to the
    # Organization and Writing Mechanics criteria.
    return join_wrapped_lines(text, boxes), boxes, low_conf
