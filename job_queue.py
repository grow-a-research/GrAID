"""
job_queue.py — Phase 21: Background asyncio queue for OCR + AI grading.

Submissions are processed one at a time in a background worker task so that
the API stays responsive during long-running OCR/grading operations.

Public API
----------
start_worker()           — schedule the background coroutine (call once from lifespan)
enqueue_submission(...)  — add a job to the queue
get_status()             — return a dict describing current queue state
"""
from __future__ import annotations

import asyncio
import difflib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Queue state
# ---------------------------------------------------------------------------

class _QueueState:
    def __init__(self) -> None:
        self.queue:          asyncio.Queue  = asyncio.Queue()
        self.current:        dict | None    = None   # {"submission_id", "label"}
        self.completed:      int            = 0
        self.failed:         int            = 0
        self.errors:         list[str]      = []
        self.total_enqueued: int            = 0
        self._task:          asyncio.Task | None = None

    def pending(self) -> int:
        return self.queue.qsize()


_STATE = _QueueState()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def enqueue_submission(submission_id: int, exam_id: int, label: str = "") -> None:
    """Add one submission to the processing queue (safe to call from sync code)."""
    job = {"submission_id": submission_id, "exam_id": exam_id, "label": label}
    _STATE.queue.put_nowait(job)
    _STATE.total_enqueued += 1
    logger.info(
        "Queue: enqueued submission %d (%s) — pending: %d",
        submission_id, label, _STATE.pending(),
    )


def get_status() -> dict:
    return {
        "pending":        _STATE.pending(),
        "current":        _STATE.current,
        "completed":      _STATE.completed,
        "failed":         _STATE.failed,
        "total_enqueued": _STATE.total_enqueued,
        "recent_errors":  _STATE.errors[-10:],
        "is_running":     _STATE._task is not None and not _STATE._task.done(),
    }


async def start_worker() -> None:
    """Create and schedule the background worker task. Call once from FastAPI lifespan."""
    _STATE._task = asyncio.create_task(_worker_loop(), name="ocr-queue-worker")
    logger.info("Queue worker started.")


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------

async def _worker_loop() -> None:
    logger.info("OCR queue worker running.")
    while True:
        try:
            job = await _STATE.queue.get()
            _STATE.current = job
            logger.info("Queue: processing submission %d", job["submission_id"])
            try:
                await asyncio.to_thread(_process_job_sync, job)
                _STATE.completed += 1
            except Exception as exc:
                _STATE.failed += 1
                msg = f"Submission {job['submission_id']} ({job.get('label', '')}): {exc}"
                _STATE.errors.append(msg)
                logger.error("Queue: job failed — %s", msg)
            finally:
                _STATE.current = None
                _STATE.queue.task_done()
        except asyncio.CancelledError:
            logger.info("Queue worker cancelled.")
            return
        except Exception as exc:
            logger.error("Queue: unexpected worker error — %s", exc)
            await asyncio.sleep(1)


# ---------------------------------------------------------------------------
# Synchronous job processor (runs in a thread via asyncio.to_thread)
# ---------------------------------------------------------------------------

def _process_job_sync(job: dict) -> None:
    """Full OCR + grading pipeline for one submission. Runs in a thread pool."""
    import cv2
    import numpy as np
    import ocr_pipeline
    from ai_grader import EssayGradeResult, correct_ocr_text, grade_essay
    from ocr_alignment import crop_content_area, crop_region, detect_and_warp
    from omr_engine import LOW_CONFIDENCE_THRESHOLD, MULTIPLE_MARKS_LABEL, detect_omr
    from PIL import Image, ImageOps

    from database import SessionLocal
    import db_models as m

    submission_id = job["submission_id"]
    db = SessionLocal()
    try:
        sub = db.get(m.Submission, submission_id)
        if not sub:
            raise ValueError("Submission not found")
        if sub.status not in ("submitted",):
            logger.info(
                "Queue: submission %d has status '%s' — skipping",
                submission_id, sub.status,
            )
            return

        exam          = db.get(m.Exam, sub.exam_id)
        template_spec = json.loads(exam.template_spec_json) if exam.template_spec_json else None
        questions: list[m.ExamQuestion] = []
        if template_spec:
            questions = (
                db.query(m.ExamQuestion)
                .filter(m.ExamQuestion.exam_id == exam.id)
                .order_by(m.ExamQuestion.order_index)
                .all()
            )

        # Fallback full-page OCR (question_id=None, from a failed alignment) can
        # only be safely graded against a real question when the exam has
        # exactly one non-MCQ/TF question — see the grading loop below.
        gradable_questions = [
            q for q in questions if (q.question_type or "essay") not in ("mcq", "tf")
        ]
        fallback_question = gradable_questions[0] if len(gradable_questions) == 1 else None

        has_non_omr = (not template_spec) or any(
            (q.question_type or "essay") not in ("mcq", "tf") for q in questions
        )
        if has_non_omr and ocr_pipeline.MODELS is None:
            raise ValueError("OCR models not loaded — start server without SKIP_MODEL_LOAD=1")

        files = (
            db.query(m.SubmissionFile)
            .filter(m.SubmissionFile.submission_id == sub.id)
            .order_by(m.SubmissionFile.page_number)
            .all()
        )
        if not files:
            raise ValueError("No files uploaded for this submission")

        project_root = Path(__file__).resolve().parent
        data_root    = project_root / "data" / "submissions"
        dest_dir     = data_root / str(sub.id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)

        # ── OCR ──────────────────────────────────────────────────────────────
        for sf in files:
            img_path = project_root / sf.stored_path
            # exif_transpose: phone photos often store pixels in the sensor's
            # native orientation with an EXIF tag saying how to rotate them
            # for display — apply that before any processing, or ArUco
            # alignment maps to the wrong physical corners once markers ARE
            # detected, even though detection itself is rotation-agnostic.
            image    = ImageOps.exif_transpose(Image.open(img_path)).convert("RGB")
            aligned  = False

            if template_spec:
                warped, aligned = detect_and_warp(image, template_spec)
                if aligned:
                    try:
                        _save_png(warped, dest_dir / f"aligned_p{sf.page_number}.png")
                    except Exception:
                        pass

                    for q in questions:
                        if not q.region_json:
                            continue
                        region = json.loads(q.region_json)
                        qtype  = (q.question_type or "essay")
                        omr_confidence: float | None = None
                        ocr_clarity:    float | None = None

                        if qtype in ("mcq", "tf") and region.get("bubbles"):
                            label, conf, _ = detect_omr(warped, region, template_spec)
                            ocr_text   = label or ""
                            boxes_data = "[]"
                            omr_confidence = conf if label else None
                            ans_status = (
                                "needs_review"
                                if not ocr_text or (
                                    omr_confidence is not None
                                    and omr_confidence < LOW_CONFIDENCE_THRESHOLD
                                )
                                else "done"
                            )
                        else:
                            crop        = crop_region(warped, region, template_spec)
                            ocr_clarity = _laplacian_var(crop)
                            ocr_text, boxes, _ = ocr_pipeline.run_ocr_pipeline(crop)
                            if qtype not in ("mcq", "tf"):
                                ocr_text = correct_ocr_text(ocr_text)
                            boxes_data = json.dumps(
                                [{"x1": b[0], "y1": b[1], "x2": b[2], "y2": b[3]}
                                 for b in boxes]
                            )
                            ans_status = "done"

                        _upsert_answer(
                            db, sub.id, q.id, sf.page_number,
                            ocr_text, boxes_data, ans_status,
                            omr_confidence, ocr_clarity, now,
                        )

            if not aligned:
                fallback    = crop_content_area(image, template_spec)
                ocr_clarity = _laplacian_var(fallback)
                ocr_text, boxes, _ = ocr_pipeline.run_ocr_pipeline(fallback)
                ocr_text   = correct_ocr_text(ocr_text)
                boxes_data = json.dumps(
                    [{"x1": b[0], "y1": b[1], "x2": b[2], "y2": b[3]} for b in boxes]
                )
                _upsert_fallback_answer(
                    db, sub.id, sf.page_number, ocr_text, boxes_data, ocr_clarity, now
                )

        sub.status = "ocr_done"
        db.commit()

        # ── Grade ─────────────────────────────────────────────────────────────
        answers = (
            db.query(m.SubmissionAnswer)
            .filter(m.SubmissionAnswer.submission_id == sub.id)
            .all()
        )
        for ans in answers:
            if not ans.ocr_text:
                continue
            question = (
                db.get(m.ExamQuestion, ans.question_id) if ans.question_id else fallback_question
            )
            qtype    = (question.question_type if question else "essay") or "essay"

            if qtype == "essay":
                result: EssayGradeResult = grade_essay(
                    question_prompt=         question.prompt                if question else "General answer",
                    rubric_text=             question.rubric_text           if question else "Grade for content and clarity.",
                    rubric_criteria_json=    question.rubric_criteria_json  if question else None,
                    max_points=              question.max_points           if question else 10.0,
                    ocr_text=                ans.ocr_text,
                )
                ans.ai_score                = result.score
                ans.ai_feedback             = result.feedback
                ans.groq_confidence         = result.confidence
                ans.ai_criteria_scores_json = result.criteria_scores_json
                ans.status                  = "graded"
                if result.score == 0.0:
                    _flag(ans, "essay_score_zero", db)
                elif result.confidence < 0.4:
                    _flag(ans, "essay_low_confidence", db)
                if ans.question_id is None and question is None:
                    ans.status = "needs_review"
                    _flag(ans, "fallback_ocr_ambiguous_question", db)

            elif qtype in ("mcq", "tf"):
                max_pts = question.max_points if question else 1.0
                if ans.ocr_text.strip() == MULTIPLE_MARKS_LABEL:
                    # Two or more bubbles were filled — invalid regardless of
                    # which mark is darkest, so it's an automatic zero.
                    ans.ai_score    = 0.0
                    ans.ai_feedback = (
                        f"Correct: {question.correct_answer}. "
                        "Detected: multiple bubbles marked. "
                        "Incorrect — more than one option was filled in, so no "
                        "single answer can be credited. ⚠ Please verify on the original scan."
                    )
                    ans.status = "needs_review"
                    _flag(ans, "omr_multiple_marks", db)
                    continue
                correct     = (question.correct_answer or "").strip().upper()
                given       = ans.ocr_text.strip().upper()
                given_first = given.split()[0] if given else ""
                match       = (given_first == correct) or (given == correct)
                ans.ai_score    = max_pts if match else 0.0
                ans.ai_feedback = (
                    f"Correct: {question.correct_answer}. "
                    f"Detected: {ans.ocr_text.strip() or '(none)'}. "
                    + ("Correct." if match else "Incorrect.")
                )
                if ans.omr_confidence is not None and ans.omr_confidence < 0.30:
                    ans.status = "needs_review"
                    _flag(ans, "omr_low_confidence", db)
                elif not ans.ocr_text.strip():
                    ans.status = "needs_review"
                    _flag(ans, "omr_no_detection", db)
                else:
                    ans.status = "graded"

            elif qtype == "identification":
                correct = (question.correct_answer or "").strip()
                given   = ans.ocr_text.strip()
                max_pts = question.max_points if question else 1.0
                if correct.lower() == given.lower():
                    score   = max_pts
                    verdict = "Exact match."
                else:
                    ratio = difflib.SequenceMatcher(
                        None, correct.lower(), given.lower()
                    ).ratio()
                    if ratio >= 0.85:
                        score   = max_pts
                        verdict = f"Accepted (fuzzy {ratio:.0%})."
                    elif ratio >= 0.60:
                        score   = max_pts * 0.5
                        verdict = f"Partial credit (fuzzy {ratio:.0%})."
                    else:
                        score   = 0.0
                        verdict = f"Incorrect (fuzzy {ratio:.0%})."
                ans.ai_score    = score
                ans.ai_feedback = f"Expected: {correct}. Your answer: {given}. {verdict}"
                ans.status      = "graded"
                if score == 0.0:
                    _flag(ans, "identification_no_match", db)

            ans.updated_at = now

        sub.status = "graded"
        db.commit()
        logger.info("Queue: submission %d done (OCR + graded).", submission_id)

    finally:
        db.close()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _laplacian_var(img) -> float:
    """Laplacian variance of a PIL image — proxy for image sharpness."""
    import cv2
    import numpy as np
    gray = np.array(img.convert("L"))
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _save_png(img, path: Path) -> None:
    import io as _io
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    path.write_bytes(buf.getvalue())


def _flag(ans, reason: str, db) -> None:
    """Idempotent auto-flag helper (mirrors _auto_flag in api_v1.py)."""
    import db_models as m
    existing = db.query(m.FlagLog).filter(
        m.FlagLog.submission_answer_id == ans.id
    ).first()
    if existing:
        existing.flag_reason = reason
    else:
        db.add(m.FlagLog(
            submission_answer_id=ans.id,
            flag_reason=reason,
            auto_flagged=True,
            auto_flagged_at=datetime.now(timezone.utc),
        ))


def _upsert_answer(
    db, sub_id, q_id, page_num,
    ocr_text, boxes_data, ans_status,
    omr_conf, ocr_clarity, now,
) -> None:
    import db_models as m
    existing = (
        db.query(m.SubmissionAnswer)
        .filter(
            m.SubmissionAnswer.submission_id == sub_id,
            m.SubmissionAnswer.question_id   == q_id,
        )
        .first()
    )
    if existing:
        existing.ocr_text       = ocr_text
        existing.boxes_json     = boxes_data
        existing.status         = ans_status
        existing.omr_confidence = omr_conf
        existing.ocr_clarity    = ocr_clarity
        existing.updated_at     = now
    else:
        db.add(m.SubmissionAnswer(
            submission_id=sub_id,
            question_id=q_id,
            page_number=page_num,
            ocr_text=ocr_text,
            boxes_json=boxes_data,
            status=ans_status,
            omr_confidence=omr_conf,
            ocr_clarity=ocr_clarity,
        ))
    db.commit()


def _upsert_fallback_answer(
    db, sub_id, page_num, ocr_text, boxes_data, ocr_clarity, now
) -> None:
    import db_models as m
    existing = (
        db.query(m.SubmissionAnswer)
        .filter(
            m.SubmissionAnswer.submission_id == sub_id,
            m.SubmissionAnswer.page_number   == page_num,
            m.SubmissionAnswer.question_id.is_(None),
        )
        .first()
    )
    if existing:
        existing.ocr_text    = ocr_text
        existing.boxes_json  = boxes_data
        existing.status      = "done"
        existing.ocr_clarity = ocr_clarity
        existing.updated_at  = now
    else:
        db.add(m.SubmissionAnswer(
            submission_id=sub_id,
            question_id=None,
            page_number=page_num,
            ocr_text=ocr_text,
            boxes_json=boxes_data,
            status="done",
            ocr_clarity=ocr_clarity,
        ))
    db.commit()
