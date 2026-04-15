"""
ai_grader.py — Phase 6: AI-powered rubric-based essay grading via Groq.

Requires:  pip install groq
           GROQ_API_KEY environment variable (get a free key at console.groq.com)

Model used: llama-3.3-70b-versatile  (free tier, fast, strong reasoning)

Public API
----------
grade_answer(prompt, rubric, max_points, ocr_text) -> GradeResult
compute_cer(reference, hypothesis) -> float
compute_wer(reference, hypothesis) -> float
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_GROQ_MODEL = "llama-3.3-70b-versatile"

# Retry configuration for Groq rate-limit / transient errors
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0   # seconds; doubles each attempt

_SYSTEM_PROMPT = """\
You are an experienced teacher grading a handwritten essay answer.
Your job is to evaluate the student's answer fairly and constructively.
Always respond with valid JSON only — no extra text before or after."""

_USER_TEMPLATE = """\
## Question
{question_prompt}

## Rubric / Marking Criteria
{rubric}

## Maximum Points
{max_points}

## Student's Answer (extracted via OCR — may contain minor transcription errors)
{ocr_text}

---

Grade this answer. Return ONLY a JSON object in this exact format:
{{
  "score": <number between 0 and {max_points}>,
  "confidence": <number between 0.0 and 1.0 — how certain you are about this score given OCR quality>,
  "feedback": "<2-4 sentences: quote specific parts of the answer, identify which parts address the rubric, note what is missing, give targeted suggestions>"
}}
"""


@dataclass
class GradeResult:
    score: float
    feedback: str
    confidence: float = 1.0   # 0–1: how certain the model is about the score
    model: str = _GROQ_MODEL


def _get_client():
    """Lazily create the Groq client (avoids import errors if groq isn't installed)."""
    try:
        from groq import Groq
    except ImportError as e:
        raise RuntimeError(
            "groq package not installed. Run: .venv\\Scripts\\python -m pip install groq"
        ) from e

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY environment variable not set. "
            "Get a free key at https://console.groq.com and set it before starting the server."
        )
    return Groq(api_key=api_key)


def _groq_call_with_retry(messages: list[dict], max_tokens: int = 512, temperature: float = 0.2) -> str:
    """
    Call Groq with exponential-backoff retry on rate-limit (429) and transient errors.

    Returns the model's response text.
    Raises the last exception if all retries are exhausted.
    """
    client = _get_client()
    delay = _RETRY_BASE_DELAY
    last_exc: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=_GROQ_MODEL,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            last_exc = exc
            exc_str = str(exc).lower()
            # Retry on rate-limit or transient server errors only
            if "rate" in exc_str or "429" in exc_str or "500" in exc_str or "503" in exc_str:
                if attempt < _MAX_RETRIES:
                    logger.warning(
                        "Groq call failed (attempt %d/%d): %s — retrying in %.1fs",
                        attempt, _MAX_RETRIES, exc, delay,
                    )
                    time.sleep(delay)
                    delay *= 2.0
                    continue
            raise

    raise last_exc  # type: ignore[misc]


def grade_answer(
    question_prompt: str,
    rubric: str,
    max_points: float,
    ocr_text: str,
) -> GradeResult:
    """
    Send a student answer to Groq and return a score + constructive feedback.

    Parameters
    ----------
    question_prompt : The exam question text.
    rubric          : The marking criteria (from ExamQuestion.rubric_text).
    max_points      : Maximum achievable score for this question.
    ocr_text        : OCR-extracted student answer.

    Returns
    -------
    GradeResult with score clamped to [0, max_points] and written feedback.
    """
    user_msg = _USER_TEMPLATE.format(
        question_prompt=question_prompt,
        rubric=rubric,
        max_points=max_points,
        ocr_text=ocr_text.strip() or "(no answer written)",
    )

    raw = _groq_call_with_retry(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        max_tokens=512,
        temperature=0.2,
    )
    logger.debug("Groq raw response: %s", raw)

    score, feedback, confidence = _parse_response(raw, max_points)
    return GradeResult(score=score, feedback=feedback, confidence=confidence)


def _parse_response(raw: str, max_points: float) -> tuple[float, str, float]:
    """Parse JSON from the model response with a regex fallback.

    Returns (score, feedback, confidence).
    confidence defaults to 1.0 when the field is absent (older responses).
    """
    # Try direct JSON parse (model usually wraps in ```json ... ```)
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    try:
        data       = json.loads(clean)
        score      = float(data["score"])
        feedback   = str(data["feedback"])
        confidence = float(data.get("confidence", 1.0))
        score      = max(0.0, min(float(max_points), score))
        confidence = max(0.0, min(1.0, confidence))
        return score, feedback, confidence
    except Exception:
        pass

    # Fallback: regex extraction
    score_match      = re.search(r'"score"\s*:\s*([\d.]+)', raw)
    feedback_match   = re.search(r'"feedback"\s*:\s*"([^"]+)"', raw, re.DOTALL)
    confidence_match = re.search(r'"confidence"\s*:\s*([\d.]+)', raw)

    score      = float(score_match.group(1))      if score_match      else 0.0
    feedback   = feedback_match.group(1)          if feedback_match   else raw[:400]
    confidence = float(confidence_match.group(1)) if confidence_match else 1.0
    score      = max(0.0, min(float(max_points), score))
    confidence = max(0.0, min(1.0, confidence))

    logger.warning("Used regex fallback to parse Groq response.")
    return score, feedback, confidence


# ── Post-OCR correction ───────────────────────────────────────────────────────

_OCR_CORRECTION_SYSTEM = """\
You are an OCR post-processor for handwritten exam answers.
The input is raw text extracted by an OCR model from a scanned answer box.
It may contain artefacts from imperfect cropping or line detection.

Step 1 — STRIP any printed question text:
  - Remove any leading line that looks like a printed question prompt
    (e.g. lines starting with "Q1.", "Q2.", "Question", or ending with "?")
  - The student's answer begins after the question prompt; keep only the answer.

Step 2 — FIX transcription errors caused by ambiguous handwriting:
  - Misread letters (e.g. 'rn' → 'm', '0' vs 'O', '1' vs 'l', 'u' vs 'n')
  - Garbled or missing special symbols
  - Run-together words caused by unclear spacing

Step 3 — RECONSTRUCT fragmented paragraphs:
  - OCR line detection may have split one continuous paragraph into many short lines.
  - Merge lines that are part of the same sentence or thought into one continuous paragraph.
  - Only preserve a line break when it clearly marks the start of a new idea or paragraph.
  - Do NOT split sentences that belong together just because they appeared on separate OCR lines.

Step 4 — RESTRUCTURE into proper essay form:
  - Capitalize the first letter of each sentence
  - End sentences with appropriate punctuation (. ? !)
  - Separate distinct paragraphs with a blank line

Rules (non-negotiable):
- Do NOT add new content, expand ideas, or rephrase meaning
- Do NOT remove content that belongs to the student's answer
- Preserve the student's own words and vocabulary
- Return ONLY the corrected and restructured answer text — no labels, no explanation"""

_ID_CORRECTION_SYSTEM = """\
You are an OCR post-processor for short handwritten identification answers.
The input is raw text extracted by an OCR model from a small answer box.
The student's answer is typically 1–5 words.

Fix ONLY character-level OCR errors caused by ambiguous handwriting:
- Misread letters (e.g. 'rn' → 'm', '0' vs 'O', '1' vs 'l', 'u' vs 'n')
- Extra or missing characters from noisy strokes
- Run-together or split words caused by unclear spacing

Rules (non-negotiable):
- Do NOT reconstruct paragraphs or add punctuation beyond what is handwritten
- Do NOT rephrase, expand, or interpret the answer
- Do NOT remove words that appear to be part of the answer
- Return ONLY the corrected short answer text — no labels, no explanation
- If the input looks completely garbled and unrecoverable, return it unchanged"""


def correct_id_text(raw_text: str) -> str:
    """
    Groq OCR post-processing for short identification answers.
    Uses a simpler character-fix-only prompt — no paragraph reconstruction or essay formatting.
    Falls back silently to raw_text on any error.
    """
    if not raw_text or not raw_text.strip():
        return raw_text
    try:
        corrected = _groq_call_with_retry(
            messages=[
                {"role": "system", "content": _ID_CORRECTION_SYSTEM},
                {"role": "user",   "content": f"Correct this short answer OCR text:\n\n{raw_text}"},
            ],
            temperature=0.1,
            max_tokens=100,
        )
        logger.info("ID OCR correction: %d → %d chars", len(raw_text), len(corrected))
        return corrected
    except Exception as e:
        logger.warning("ID OCR correction skipped (using raw text): %s", e)
        return raw_text


def correct_ocr_text(raw_text: str) -> str:
    """
    Send raw Qwen OCR output to Groq for post-processing cleanup.

    Fixes garbled characters and ambiguous symbol transcriptions without
    adding or rephrasing content. Falls back silently to raw_text on any error
    (no API key, rate-limit, network issue) so OCR always completes.
    """
    if not raw_text or not raw_text.strip():
        return raw_text
    try:
        corrected = _groq_call_with_retry(
            messages=[
                {"role": "system", "content": _OCR_CORRECTION_SYSTEM},
                {"role": "user",   "content": f"Correct this OCR text:\n\n{raw_text}"},
            ],
            temperature=0.1,
            max_tokens=min(2048, len(raw_text) * 2 + 200),
        )
        logger.info("OCR correction: %d → %d chars", len(raw_text), len(corrected))
        return corrected
    except Exception as e:
        logger.warning("OCR correction skipped (using raw text): %s", e)
        return raw_text


# ── AI analytics insights ─────────────────────────────────────────────────────

_EXAM_ANALYSIS_SYSTEM = """\
You are an educational data analyst helping a teacher understand their students' performance.
Analyze the exam data provided and give 3-5 concise, actionable bullet points.
Focus on: which questions were hardest/easiest, overall pass rate interpretation,
patterns worth noting, and one concrete suggestion for the teacher.
Use plain language. No filler phrases. Return plain text, no markdown headers."""

_STUDENT_ANALYSIS_SYSTEM = """\
You are an educational advisor reviewing a student's performance across multiple exams.
Analyze the data and give 3-5 concise bullet points covering: performance trend,
strongest and weakest areas if discernible, consistency, and one actionable recommendation
for the teacher or student. Use plain language. Return plain text, no markdown headers."""


def analyze_exam_performance(stats: dict) -> str:
    """
    Generate AI insights for an exam's analytics data.
    `stats` is a dict-serialized ExamStats object.
    Returns plain text analysis from Groq.
    """
    client = _get_client()

    q_lines = "\n".join(
        f"  Q{q['order_index']} ({q['max_points']} pts): "
        f"avg={q['avg_score'] if q['avg_score'] is not None else 'no data'}, "
        f"min={q['min_score']}, max={q['max_score']}, n={q['answer_count']}\n"
        f"  Prompt: {q['prompt']}"
        for q in stats["questions"]
    )

    user_msg = (
        f"Exam: {stats['exam_code']} — {stats['title']}\n"
        f"Submissions: {stats['submission_count']} total, {stats['graded_count']} graded\n"
        f"Max possible: {stats['max_possible']}\n"
        f"Class average: {stats.get('avg_total')} pts ({stats.get('avg_pct')}%)\n"
        f"Pass: {stats['pass_count']}  Fail: {stats['fail_count']}  (threshold: 60%)\n\n"
        f"Per-question results:\n{q_lines}"
    )

    return _groq_call_with_retry(
        messages=[
            {"role": "system", "content": _EXAM_ANALYSIS_SYSTEM},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.3,
        max_tokens=600,
    )


def analyze_student_performance(stats: dict) -> str:
    """
    Generate AI insights for a student's submission history.
    `stats` is a dict-serialized StudentAnalytics object.
    Returns plain text analysis from Groq.
    """
    sub_lines = "\n".join(
        f"  {s['exam_code']} ({s['class_code']}): "
        f"{s['total_score']}/{s['max_possible']} = {s['pct']}%  [{s['status']}]"
        if s['total_score'] is not None
        else f"  {s['exam_code']} ({s['class_code']}): not yet graded  [{s['status']}]"
        for s in stats["submissions"]
    )

    user_msg = (
        f"Student: {stats['full_name']} ({stats['student_id']})\n"
        f"Total submissions: {len(stats['submissions'])}\n\n"
        f"Submission history:\n{sub_lines if sub_lines else '  (none)'}"
    )

    return _groq_call_with_retry(
        messages=[
            {"role": "system", "content": _STUDENT_ANALYSIS_SYSTEM},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.3,
        max_tokens=500,
    )


# ── OCR quality metrics ────────────────────────────────────────────────────────

def _edit_distance(a: list, b: list) -> int:
    """Standard dynamic-programming Levenshtein distance."""
    m, n = len(a), len(b)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, n + 1):
            temp = dp[j]
            dp[j] = prev if a[i - 1] == b[j - 1] else 1 + min(prev, dp[j], dp[j - 1])
            prev = temp
    return dp[n]


def compute_cer(reference: str, hypothesis: str) -> float:
    """
    Character Error Rate = edit_distance(ref_chars, hyp_chars) / len(ref_chars).
    Returns 0.0 if reference is empty.
    """
    ref = list(reference)
    hyp = list(hypothesis)
    if not ref:
        return 0.0
    return _edit_distance(ref, hyp) / len(ref)


def compute_wer(reference: str, hypothesis: str) -> float:
    """
    Word Error Rate = edit_distance(ref_words, hyp_words) / len(ref_words).
    Returns 0.0 if reference is empty.
    """
    ref = reference.split()
    hyp = hypothesis.split()
    if not ref:
        return 0.0
    return _edit_distance(ref, hyp) / len(ref)
