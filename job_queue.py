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
import json
import logging
import time
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
    from identification_scoring import score_identification
    from ocr_alignment import crop_content_area, crop_region, detect_and_warp
    from omr_engine import LOW_CONFIDENCE_THRESHOLD, MULTIPLE_MARKS_LABEL, detect_omr
    from PIL import Image, ImageOps

    from database import SessionLocal
    import db_models as m

    submission_id = job["submission_id"]
    job_start = time.perf_counter()
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
        # Questions already written during THIS run — a later page continues
        # them instead of overwriting (mirrors _merge_page_text in api_v1.py).
        written_questions: set[int] = set()

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
                t0 = time.perf_counter()
                warped, aligned = detect_and_warp(image, template_spec)
                logger.info(
                    "[Timing] submission %d p%d: align/warp took %.2fs",
                    submission_id, sf.page_number, time.perf_counter() - t0,
                )
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
                            crop        = crop_region(
                                warped, region, template_spec,
                                snap_to_box=(qtype == "identification"),
                                top_padding_mm=_TOP_PAD_MM.get(qtype, _DEFAULT_TOP_PAD_MM),
                            )
                            ocr_clarity = _laplacian_var(crop)
                            t_ocr = time.perf_counter()
                            ocr_text, boxes, ocr_low_conf = _ocr_answer_crop(crop, qtype)
                            logger.info(
                                "[Timing] submission %d q%d: remote OCR call took %.2fs",
                                submission_id, q.id, time.perf_counter() - t_ocr,
                            )
                            if not ocr_text.strip():
                                # A legible crop returning zero text is a known transient
                                # hiccup on the remote OCR service, not a bad crop — one
                                # retry usually recovers it (confirmed by hand: replaying
                                # the exact same crop through the pipeline succeeds).
                                logger.warning(
                                    "submission %d q%d: OCR returned empty text — retrying once",
                                    submission_id, q.id,
                                )
                                ocr_text, boxes, ocr_low_conf = _ocr_answer_crop(crop, qtype)

                            # Identification answers keep the raw OCR text: exact-match
                            # scoring needs what the student actually wrote, and Groq
                            # correction can't tell an OCR slip from a student's own
                            # misspelling (it both removed and granted credit that way).
                            # Essays keep the transcription as OCR'd as well —
                            # see run_submission_ocr in api_v1.py.
                            if qtype not in ("mcq", "tf", "identification") and ocr_text.strip():
                                from text_normalize import strip_printed_prompt
                                ocr_text = strip_printed_prompt(ocr_text, q.prompt)
                            boxes_data = json.dumps(
                                [{"x1": b[0], "y1": b[1], "x2": b[2], "y2": b[3]}
                                 for b in boxes]
                            )
                            # Low OCR confidence never alters ocr_text (see
                            # run_ocr_pipeline) — it only routes the answer to
                            # human review instead of silently marking it done.
                            ans_status = (
                                "needs_review" if (not ocr_text.strip() or ocr_low_conf) else "done"
                            )

                        ans = _upsert_answer(
                            db, sub.id, q.id, sf.page_number,
                            ocr_text, boxes_data, ans_status,
                            omr_confidence, ocr_clarity, now,
                            append=q.id in written_questions,
                        )
                        written_questions.add(q.id)
                        if qtype not in ("mcq", "tf") and ocr_low_conf:
                            _flag(ans, "ocr_low_confidence", db)

            if not aligned:
                fallback    = crop_content_area(image, template_spec)
                ocr_clarity = _laplacian_var(fallback)
                t_ocr = time.perf_counter()
                ocr_text, boxes, _, ocr_low_conf = ocr_pipeline.run_ocr_pipeline(fallback, include_boxed_image=False)
                logger.info(
                    "[Timing] submission %d p%d: remote OCR call (fallback) took %.2fs",
                    submission_id, sf.page_number, time.perf_counter() - t_ocr,
                )
                t_corr = time.perf_counter()
                ocr_text   = correct_ocr_text(ocr_text)
                logger.info(
                    "[Timing] submission %d p%d: Groq OCR-correction call (fallback) took %.2fs",
                    submission_id, sf.page_number, time.perf_counter() - t_corr,
                )
                boxes_data = json.dumps(
                    [{"x1": b[0], "y1": b[1], "x2": b[2], "y2": b[3]} for b in boxes]
                )
                fallback_status = "needs_review" if ocr_low_conf else "done"
                fb_ans = _upsert_fallback_answer(
                    db, sub.id, sf.page_number, ocr_text, boxes_data, ocr_clarity, now,
                    fallback_status,
                )
                if ocr_low_conf:
                    _flag(fb_ans, "ocr_low_confidence", db)

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
                t_grade = time.perf_counter()
                result: EssayGradeResult = grade_essay(
                    question_prompt=         question.prompt                if question else "General answer",
                    rubric_text=             question.rubric_text           if question else "Grade for content and clarity.",
                    rubric_criteria_json=    question.rubric_criteria_json  if question else None,
                    max_points=              question.max_points           if question else 10.0,
                    ocr_text=                ans.ocr_text,
                )
                logger.info(
                    "[Timing] submission %d ans%d: Groq grading call took %.2fs",
                    submission_id, ans.id, time.perf_counter() - t_grade,
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
                score, ans.ai_feedback = score_identification(
                    question.correct_answer, ans.ocr_text,
                    question.max_points, question.case_sensitive,
                )
                ans.ai_score = score
                _flag_identification(ans, question.correct_answer, score, db)

            ans.updated_at = now

        sub.status = "graded"
        db.commit()
        logger.info(
            "Queue: submission %d done (OCR + graded) — total %.2fs",
            submission_id, time.perf_counter() - job_start,
        )

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


# Per-question-type top margin for answer crops — see api_v1.py's copy.
_DEFAULT_TOP_PAD_MM = 0.5
_TOP_PAD_MM = {"essay": -1.5}


def _ocr_answer_crop(crop, qtype: str) -> tuple[str, list, bool]:
    """OCR one answer crop (mirrors _ocr_answer_crop in api_v1.py): identification
    boxes go to the single-line path, essays to the two-scale pass, everything
    else to the plain pipeline."""
    import ocr_pipeline
    if qtype == "identification":
        from id_ocr_client import run_identification_ocr
        return run_identification_ocr(crop)
    if qtype == "essay":
        from essay_ocr import run_essay_ocr
        return run_essay_ocr(crop)
    text, boxes, _, low_conf = ocr_pipeline.run_ocr_pipeline(crop, include_boxed_image=False)
    return text, boxes, low_conf


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


def _flag_identification(ans, correct_answer, score: float, db) -> None:
    """Status + auto-flag for a scored identification answer (mirrors
    _flag_identification in api_v1.py). Must run before ans.status is
    overwritten, since it reads the OCR step's needs_review status."""
    import db_models as m
    from identification_scoring import looks_unreadable
    if score > 0.0:
        ans.status = "graded"
        # Drop a stale auto-flag from an earlier grade; keep manual or reviewed ones.
        db.query(m.FlagLog).filter(
            m.FlagLog.submission_answer_id == ans.id,
            m.FlagLog.auto_flagged.is_(True),
            m.FlagLog.review_decision.is_(None),
        ).delete(synchronize_session=False)
    elif ans.status == "needs_review" or looks_unreadable(correct_answer, ans.ocr_text):
        ans.status = "needs_review"
        _flag(ans, "identification_ocr_unreadable", db)
    else:
        ans.status = "graded"
        _flag(ans, "identification_no_match", db)


def _upsert_answer(
    db, sub_id, q_id, page_num,
    ocr_text, boxes_data, ans_status,
    omr_conf, ocr_clarity, now,
    append: bool = False,
):
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
        # append=True means a later page of the same submission in this run:
        # a two-page essay continues its answer instead of replacing it.
        from routers.api_v1 import _merge_page_text
        existing.ocr_text       = _merge_page_text(existing.ocr_text, ocr_text, append)
        existing.boxes_json     = boxes_data
        existing.status         = ans_status
        existing.omr_confidence = omr_conf
        existing.ocr_clarity    = ocr_clarity
        existing.updated_at     = now
        ans = existing
    else:
        ans = m.SubmissionAnswer(
            submission_id=sub_id,
            question_id=q_id,
            page_number=page_num,
            ocr_text=ocr_text,
            boxes_json=boxes_data,
            status=ans_status,
            omr_confidence=omr_conf,
            ocr_clarity=ocr_clarity,
        )
        db.add(ans)
    db.commit()
    return ans


def _upsert_fallback_answer(
    db, sub_id, page_num, ocr_text, boxes_data, ocr_clarity, now, ans_status="done"
):
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
        existing.status      = ans_status
        existing.ocr_clarity = ocr_clarity
        existing.updated_at  = now
        ans = existing
    else:
        ans = m.SubmissionAnswer(
            submission_id=sub_id,
            question_id=None,
            page_number=page_num,
            ocr_text=ocr_text,
            boxes_json=boxes_data,
            status=ans_status,
            ocr_clarity=ocr_clarity,
        )
        db.add(ans)
    db.commit()
    return ans
