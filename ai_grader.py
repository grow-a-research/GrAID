"""
ai_grader.py — Phase 6: AI-powered rubric-based essay grading via Groq.

Requires:  pip install groq
           GROQ_API_KEY environment variable (get a free key at console.groq.com)

Model used: llama-3.3-70b-versatile  (free tier, fast, strong reasoning)

Public API
----------
grade_answer(prompt, rubric, max_points, ocr_text) -> GradeResult
grade_essay(prompt, rubric_text, rubric_criteria_json, max_points, ocr_text) -> EssayGradeResult
    Dispatcher call sites should use — grades per-criterion when a structured
    rubric is present, else falls back to the legacy holistic grade_answer() path.
compute_cer(reference, hypothesis) -> float
compute_wer(reference, hypothesis) -> float
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field

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


# ── Structured (per-criterion) rubric grading ──────────────────────────────────

@dataclass
class CriterionScore:
    criterion: str
    max_points: float
    score: float
    justification: str
    level: str = ""   # label of the rubric level band the final score falls in


@dataclass
class StructuredGradeResult:
    criteria_scores: list[CriterionScore]
    score: float            # Python-computed sum of criteria_scores, clamped to [0, max_points]
    feedback: str           # synthesized summary, for callers that only read one feedback string
    confidence: float
    model: str = _GROQ_MODEL


@dataclass
class EssayGradeResult:
    """Common return type for grade_essay() — the structured/legacy dispatcher."""
    score: float
    feedback: str
    confidence: float
    criteria_scores_json: str | None = None   # None for the legacy free-text path


_STRUCTURED_SYSTEM_PROMPT = """\
You are an experienced teacher grading a handwritten essay answer against a
rubric with multiple criteria. Score EACH criterion independently and fairly.

Each rubric level below defines a NUMERIC BAND (e.g. "Excellent: score 8-10
pts"). For each criterion: first decide which level's description best
matches the answer, then pick a score WITHIN that level's band — the top of
the band for a strong match to that level's description, the bottom of the
band for a weaker-but-still-that-level match. Never pick a score outside the
band of the level you judged the answer to match.

Do NOT compute or report a total/overall score — only per-criterion scores.
Always respond with valid JSON only — no extra text before or after."""

_STRUCTURED_USER_TEMPLATE = """\
## Question
{question_prompt}

## Rubric — grade each criterion below independently
{criteria_block}

## Student's Answer (extracted via OCR — may contain minor transcription errors)
{ocr_text}

---

Grade this answer against EACH criterion above. Return ONLY a JSON array, one
object per criterion, in the same order as listed, in this exact format:
[
  {{
    "criterion": "<criterion name, exactly as given above>",
    "score": <number between 0 and that criterion's max points>,
    "confidence": <number between 0.0 and 1.0 — how certain you are about this criterion's score given OCR quality>,
    "justification": "<1-2 sentences: quote specific parts of the answer relevant to this criterion, note what is present or missing>"
  }},
  ...
]
Do NOT include a total or overall score anywhere in your response.
"""


def _compute_level_bands(levels: list[dict], max_points: float) -> list[dict]:
    """
    Derive non-overlapping numeric score bands from a criterion's performance
    levels, so a continuous score can be explained in terms of which
    qualitative level it falls under.

    Levels are sorted by points descending. Each band's lower boundary is the
    midpoint between its own points and the next-lower level's points; the
    top band's ceiling is max_points and the bottom band's floor is 0 — the
    bands partition [0, max_points] with no gaps or overlaps. Returns [] if
    there are no levels (nothing to band).
    """
    sorted_levels = sorted(levels, key=lambda lv: float(lv.get("points", 0) or 0), reverse=True)
    bands: list[dict] = []
    for i, lvl in enumerate(sorted_levels):
        upper = float(max_points) if i == 0 else bands[i - 1]["lower"]
        if i < len(sorted_levels) - 1:
            next_points = float(sorted_levels[i + 1].get("points", 0) or 0)
            lower = (float(lvl.get("points", 0) or 0) + next_points) / 2.0
        else:
            lower = 0.0
        bands.append({
            "label": lvl.get("label", ""),
            "description": lvl.get("description", ""),
            "upper": upper,
            "lower": lower,
        })
    return bands


def _level_for_score(score: float, bands: list[dict]) -> str:
    """Label of the band containing `score` (bands fully partition [0, max_points])."""
    for b in bands:
        if b["lower"] - 1e-9 <= score <= b["upper"] + 1e-9:
            return b["label"]
    return bands[-1]["label"] if bands else ""


def _render_criteria_for_prompt(criteria: list[dict]) -> str:
    """Render structured rubric criteria — with computed score bands — for the grading prompt."""
    lines: list[str] = []
    for c in criteria:
        c_max = float(c.get("max_points", 0) or 0)
        bands = _compute_level_bands(c.get("levels", []) or [], c_max)
        lines.append(f"### {c.get('name', 'Criterion')} (score 0–{c_max:g} pts)")
        for b in bands:
            lines.append(
                f"- {b['label']}: score {b['lower']:g}-{b['upper']:g} pts — {b['description']}"
            )
    return "\n".join(lines)


def _parse_structured_response(raw: str, criteria: list[dict]) -> list[dict]:
    """
    Parse the model's per-criterion JSON array, tolerant of formatting issues.

    Returns one dict per input criterion (same order), each with
    {criterion, max_points, score, confidence, justification}. Any criterion
    the model didn't return a usable object for gets a zero score and a
    "no response" justification rather than being dropped.
    """
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    parsed_items: list[dict] = []
    try:
        data = json.loads(clean)
        if isinstance(data, list):
            parsed_items = [item for item in data if isinstance(item, dict)]
    except Exception:
        pass

    if not parsed_items:
        for m in re.finditer(r'\{[^{}]*"criterion"[^{}]*\}', raw, re.DOTALL):
            try:
                parsed_items.append(json.loads(m.group(0)))
            except Exception:
                continue
        if parsed_items:
            logger.warning("Used regex fallback to parse structured Groq response.")

    by_name = {
        str(item.get("criterion", "")).strip().lower(): item
        for item in parsed_items
        if str(item.get("criterion", "")).strip()
    }

    results: list[dict] = []
    for idx, c in enumerate(criteria):
        c_name = str(c.get("name") or f"Criterion {idx + 1}")
        c_max = float(c.get("max_points", 0) or 0)
        bands = _compute_level_bands(c.get("levels", []) or [], c_max)
        item = by_name.get(c_name.strip().lower())
        if item is None and idx < len(parsed_items):
            item = parsed_items[idx]  # positional fallback if names don't match

        if item is None:
            results.append({
                "criterion": c_name,
                "max_points": c_max,
                "score": 0.0,
                "confidence": 0.0,
                "justification": "(no response for this criterion — review manually)",
                "level": bands[-1]["label"] if bands else "",
            })
            continue

        try:
            score = max(0.0, min(c_max, float(item.get("score", 0))))
        except Exception:
            score = 0.0
        try:
            confidence = max(0.0, min(1.0, float(item.get("confidence", 1.0))))
        except Exception:
            confidence = 1.0
        justification = str(item.get("justification") or "").strip() or "(no justification provided)"

        results.append({
            "criterion": c_name,
            "max_points": c_max,
            "score": score,
            "confidence": confidence,
            "justification": justification,
            # Derived from the final (clamped) score, not asked of the model —
            # keeps "which level" consistent with "what score" by construction.
            "level": _level_for_score(score, bands) if bands else "",
        })

    return results


def grade_answer_structured(
    question_prompt: str,
    criteria: list[dict],
    max_points: float,
    ocr_text: str,
) -> StructuredGradeResult:
    """
    Grade an essay answer criterion-by-criterion in a single Groq call.

    The model scores each criterion independently and is explicitly told not
    to compute a total; the total returned here is always summed in Python
    from the per-criterion scores, never trusted from the model's output.
    """
    criteria_block = _render_criteria_for_prompt(criteria)
    user_msg = _STRUCTURED_USER_TEMPLATE.format(
        question_prompt=question_prompt,
        criteria_block=criteria_block,
        ocr_text=ocr_text.strip() or "(no answer written)",
    )

    raw = _groq_call_with_retry(
        messages=[
            {"role": "system", "content": _STRUCTURED_SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        max_tokens=min(2048, 300 + 200 * max(1, len(criteria))),
        temperature=0.2,
    )
    logger.debug("Groq raw structured response: %s", raw)

    items = _parse_structured_response(raw, criteria)
    criteria_scores = [
        CriterionScore(
            criterion=i["criterion"], max_points=i["max_points"],
            score=i["score"], justification=i["justification"], level=i.get("level", ""),
        )
        for i in items
    ]
    total = max(0.0, min(float(max_points), sum(cs.score for cs in criteria_scores)))
    confidences = [i["confidence"] for i in items]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 1.0

    feedback = "; ".join(
        f"{cs.criterion}: {cs.score:g}/{cs.max_points:g}"
        f"{f' ({cs.level})' if cs.level else ''} — {cs.justification}"
        for cs in criteria_scores
    )
    if len(feedback) > 1500:
        feedback = feedback[:1497] + "..."

    return StructuredGradeResult(
        criteria_scores=criteria_scores, score=total, feedback=feedback, confidence=avg_confidence,
    )


def grade_essay(
    question_prompt: str,
    rubric_text: str | None,
    rubric_criteria_json: str | None,
    max_points: float,
    ocr_text: str,
) -> EssayGradeResult:
    """
    Single entry point essay-grading call sites should use in place of
    grade_answer() directly. Grades per-criterion when a structured rubric
    is available and parses cleanly; otherwise falls back to the legacy
    holistic rubric_text prompt, and finally to a generic instruction if
    neither is present — the same three-level fallback the call sites
    already relied on implicitly before this feature existed.
    """
    criteria: list[dict] | None = None
    if rubric_criteria_json:
        try:
            parsed = json.loads(rubric_criteria_json)
            if isinstance(parsed, list) and parsed:
                criteria = parsed
        except Exception:
            logger.warning("rubric_criteria_json failed to parse — falling back to rubric_text")

    if criteria:
        try:
            r = grade_answer_structured(question_prompt, criteria, max_points, ocr_text)
            return EssayGradeResult(
                score=r.score,
                feedback=r.feedback,
                confidence=r.confidence,
                criteria_scores_json=json.dumps([asdict(cs) for cs in r.criteria_scores]),
            )
        except Exception as e:
            logger.error("Structured grading failed (%s) — falling back to flattened rubric text", e)
            rubric_text = rubric_text or _render_criteria_for_prompt(criteria)

    r = grade_answer(
        question_prompt, rubric_text or "Grade for content and clarity.", max_points, ocr_text,
    )
    return EssayGradeResult(score=r.score, feedback=r.feedback, confidence=r.confidence, criteria_scores_json=None)


# ── Post-OCR correction ───────────────────────────────────────────────────────

# Phrases that only show up when the correction model narrates its own output
# instead of just returning it (a known llama-3.3-70b failure mode on messy
# handwriting input) — e.g. "However, the above response still has run-on
# lines. Here is the reformatted text:" or "Treaty of Maastricht does not
# match, however a possible correction is: ...". If any of these leak through,
# the "corrected" text is unusable and unsafe to grade against.
_RUNAWAY_MARKERS = (
    "here is the reformatted",
    "the above response",
    "does not match",
    "does not seem correct",
    "a possible correction is",
    "let me",
    "as an ai",
    "i apologize",
)


def _looks_like_runaway_correction(raw_text: str, corrected: str) -> bool:
    """Detect a Groq correction response that leaked meta-commentary/self-critique
    instead of a clean corrected answer, so callers can fall back to raw OCR text."""
    lowered = corrected.lower()
    if any(marker in lowered for marker in _RUNAWAY_MARKERS):
        return True
    # A layout/character-level cleanup pass should never balloon the text —
    # runaway generations repeat the answer across several restated drafts.
    if len(corrected) > max(200, len(raw_text) * 3):
        return True
    return False

_OCR_CORRECTION_SYSTEM = """\
You are a text LAYOUT cleaner for OCR output of handwritten exam answers.
You do not have access to the original image — only the raw transcribed
text — so you have no way to tell whether an odd spelling is a genuine
mistake the student made or a misread by the OCR model. Since grading may
score spelling/grammar as part of the rubric, you must never guess at
content: treat every word exactly as transcribed, right or wrong.

Your ONLY job is to fix how the text is LAID OUT, never what it says:

1. STRIP a leading printed question line, if present:
   - Remove a leading line that looks like a printed question prompt
     (e.g. starts with "Q1.", "Question", or ends with "?")
   - Keep only the student's answer text.

2. MERGE fragmented lines into paragraphs:
   - OCR line detection may have split one continuous paragraph into many
     short lines. Merge lines that are part of the same sentence/thought
     into one continuous paragraph.
   - Only keep a line break where it clearly marks the start of a new
     paragraph.

3. Separate distinct paragraphs with a blank line.

Absolutely forbidden, even if it looks like an "obvious" fix:
- Do NOT fix spelling — a misspelled word must stay exactly as transcribed
- Do NOT fix grammar or word choice
- Do NOT add, remove, or change any punctuation as a "correction" (only the
  paragraph-break blank lines from rule 3 above are allowed)
- Do NOT change, merge, or split any letters/words, even if the result
  looks like a typo — an accidental "fix" here can erase a genuine student
  mistake the rubric is meant to grade
- Do NOT rephrase, expand, add content, or interpret meaning
- Do NOT talk about your own output. Never write things like "here is the
  reformatted text", "however, the above still has...", or any other
  narration about what you just did or are about to do — you have exactly
  ONE attempt, output the answer and stop.

Return ONLY the cleaned-up text itself — nothing else. No labels, no
explanation, no meta-commentary, no multiple drafts."""

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
- Do NOT talk about your own output. Never write things like "does not
  match", "a possible correction is", or any other narration about what
  you're doing — you have exactly ONE attempt, output the answer and stop.
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
        if _looks_like_runaway_correction(raw_text, corrected):
            logger.warning(
                "ID OCR correction looked like a runaway/self-narrating response "
                "(using raw text instead): %r", corrected,
            )
            return raw_text
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
    if os.getenv("SKIP_OCR_CORRECTION") == "1":
        logger.info("OCR correction skipped (SKIP_OCR_CORRECTION=1) — using raw Qwen text.")
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
        if _looks_like_runaway_correction(raw_text, corrected):
            logger.warning(
                "OCR correction looked like a runaway/self-narrating response "
                "(using raw text instead): %r", corrected[:200],
            )
            return raw_text
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
