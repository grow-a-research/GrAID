"""
answer_confidence.py — combined transcription + grading confidence for essays.

Why a combined number at all
----------------------------
An essay score passes through two independent stages that can each be wrong:
Qwen transcribes the handwriting, then gpt-oss-120b grades the transcription.
Each stage reports its own confidence, but they are on different scales and
were previously thresholded separately, so there was no single value to quote
for "how much do we trust this score".

Why the raw minimum is not used
-------------------------------
The two numbers are not comparable as-is:

  * OCR confidence is Qwen's lowest per-token probability along a line.
    Genuine lines observed on real submissions run ~0.28-0.60, and the review
    threshold is 0.15 (see ocr_pipeline.run_ocr_pipeline).
  * Grading confidence is the model's own 0-1 self-report, thresholded at 0.40
    (see ai_grader and the essay_low_confidence flag).

min(0.30, 0.90) = 0.30 would look alarming when the 0.30 is a perfectly
ordinary OCR reading comfortably above its own threshold. So each signal is
first divided by the threshold it is actually judged against, which puts both
on a common "margin" scale where 1.0 means exactly at the limit:

    ocr_margin  = ocr_confidence  / OCR_THRESHOLD
    groq_margin = groq_confidence / GROQ_THRESHOLD
    combined    = min(ocr_margin, groq_margin)

combined < 1.0 means at least one stage fell below its own threshold, which is
exactly the old two-rule behaviour — but now as one interpretable number whose
distance from 1.0 says how close the call was. An answer is only as
trustworthy as its weakest stage.

Unknown inputs
--------------
Either input may be None: OCR confidence is absent on answers transcribed by
an OCR server build that predates the numeric field, and grading confidence is
absent on answers that were never graded. None means unknown, never "low" — an
unknown stage is skipped rather than assumed bad, and when nothing is known
the result is None and no flag is raised on this basis. Inventing a value here
would put fabricated numbers into the flag statistics.
"""
from __future__ import annotations

import os

# Each threshold is the one its own signal was already judged against, so the
# combined rule stays behaviourally identical to the two separate rules it
# replaces. Overridable for calibration without a code change.
OCR_THRESHOLD: float = float(os.getenv("OCR_MIN_LINE_CONFIDENCE", "0.15"))
GROQ_THRESHOLD: float = float(os.getenv("GROQ_MIN_CONFIDENCE", "0.40"))

# combined < this is "below at least one threshold". Kept named rather than
# inlined as 1.0 so the reason a bare number appears in the flag rule is
# greppable from the flag itself.
COMBINED_FLAG_THRESHOLD: float = 1.0


def combined_confidence(
    ocr_confidence: float | None,
    groq_confidence: float | None,
) -> float | None:
    """
    Return the combined confidence margin, or None when neither stage
    reported a usable number.

    The result is a ratio, not a probability: 1.0 sits exactly on the
    threshold, 2.0 is twice as confident as the threshold requires, and
    anything below 1.0 warrants review.
    """
    margins: list[float] = []
    if ocr_confidence is not None and OCR_THRESHOLD > 0:
        margins.append(ocr_confidence / OCR_THRESHOLD)
    if groq_confidence is not None and GROQ_THRESHOLD > 0:
        margins.append(groq_confidence / GROQ_THRESHOLD)
    if not margins:
        return None
    return min(margins)


def weakest_stage(
    ocr_confidence: float | None,
    groq_confidence: float | None,
) -> str | None:
    """
    Which stage dragged the combined value down: "transcription", "grading",
    or None if nothing is known. Used to say *why* an answer was flagged
    instead of only that it was.
    """
    ocr_margin = (
        ocr_confidence / OCR_THRESHOLD
        if ocr_confidence is not None and OCR_THRESHOLD > 0 else None
    )
    groq_margin = (
        groq_confidence / GROQ_THRESHOLD
        if groq_confidence is not None and GROQ_THRESHOLD > 0 else None
    )
    if ocr_margin is None and groq_margin is None:
        return None
    if groq_margin is None:
        return "transcription"
    if ocr_margin is None:
        return "grading"
    return "transcription" if ocr_margin <= groq_margin else "grading"


def should_flag(
    ocr_confidence: float | None,
    groq_confidence: float | None,
) -> bool:
    """
    True when the answer should go to teacher review on confidence grounds.

    False when nothing is known — an answer is never flagged for a confidence
    that was never measured.
    """
    combined = combined_confidence(ocr_confidence, groq_confidence)
    return combined is not None and combined < COMBINED_FLAG_THRESHOLD


def flag_reason(
    ocr_confidence: float | None,
    groq_confidence: float | None,
) -> str | None:
    """The FlagLog reason code for this answer, or None if it should not be flagged."""
    if not should_flag(ocr_confidence, groq_confidence):
        return None
    stage = weakest_stage(ocr_confidence, groq_confidence)
    return (
        "essay_low_transcription_confidence"
        if stage == "transcription"
        else "essay_low_grading_confidence"
    )
