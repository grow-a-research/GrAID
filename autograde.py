"""Automatic grading once an exam's deadline has passed.

For exams where the teacher turned "auto-grade" on (a deadline is required):
  1. When the deadline passes, students can no longer submit, edit or unsubmit
     (see exam_is_closed — also enforced by the student endpoints).
  2. The scheduler queues every *submitted* paper on the same queue the
     "Process" button uses. It does not change how grading itself works.
  3. When the queue drains the teacher gets a notification with the counts.
Results are never shown to students by this: releasing them stays manual.

A tick runs every few seconds-to-minutes in the event loop thread, because the
queue (asyncio.Queue) is not thread-safe. Exams with auto-grade off are never
touched.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_INTERVAL_S = 30
_task: asyncio.Task | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def exam_is_closed(exam) -> bool:
    """Students can no longer change their submission for this exam."""
    if not getattr(exam, "auto_grade", False):
        return False
    if exam.auto_grade_started_at is not None:
        return True            # once grading began it stays closed, even if the deadline moves
    return exam.due_at is not None and exam.due_at <= _now()


def _start_due_exams(db) -> None:
    import db_models as m
    from job_queue import enqueue_submission
    from notifications import notify

    due = (
        db.query(m.Exam)
        .filter(
            m.Exam.auto_grade.is_(True),
            m.Exam.auto_grade_started_at.is_(None),
            m.Exam.due_at.isnot(None),
            m.Exam.due_at <= _now(),
        )
        .all()
    )
    for exam in due:
        subs = db.query(m.Submission).filter(m.Submission.exam_id == exam.id).all()
        queued = [s for s in subs if s.status == "submitted"]
        drafts = [s for s in subs if s.status == "draft" and len(s.files) > 0]
        enrolled = db.query(m.Enrollment).filter(m.Enrollment.class_id == exam.class_id).count()
        not_submitted = max(enrolled - len(queued) - len([s for s in subs if s.status not in ("draft", "submitted")]), 0)

        for s in queued:
            student = db.get(m.Student, s.student_id)
            enqueue_submission(s.id, exam.id, f"{student.full_name} (#{s.id})" if student else f"#{s.id}")

        exam.auto_grade_started_at = _now()
        if not queued:
            exam.auto_grade_finished_at = exam.auto_grade_started_at
        db.commit()

        parts = [f"{len(queued)} submitted paper{'s' if len(queued) != 1 else ''} queued for grading"]
        if not_submitted:
            extra = f" ({len(drafts)} had pages uploaded but never pressed Submit)" if drafts else ""
            parts.append(f"{not_submitted} student{'s' if not_submitted != 1 else ''} did not submit{extra}")
        notify(db, exam, "autograde_started", f"Deadline passed — {exam.title}",
               ". ".join(parts) + ".", link_tab="submissions")
        logger.info("Auto-grade: exam %d started with %d paper(s)", exam.id, len(queued))


def _finish_started_exams(db) -> None:
    import db_models as m
    from job_queue import _STATE
    from notifications import notify
    from routers.api_v1 import _graded_answers, _needs_attention

    if _STATE.pending() > 0 or _STATE.current is not None:
        return   # still working

    started = (
        db.query(m.Exam)
        .filter(m.Exam.auto_grade_started_at.isnot(None), m.Exam.auto_grade_finished_at.is_(None))
        .all()
    )
    for exam in started:
        subs, graded_subs, answers_by_key = _graded_answers(exam, db)
        waiting = [s for s in subs if s.status == "submitted"]     # failed, or lost on a restart
        review = sum(1 for a in answers_by_key.values() if _needs_attention(a))

        exam.auto_grade_finished_at = _now()
        db.commit()

        body = f"{len(graded_subs)} graded · {review} answer{'s' if review != 1 else ''} need your review"
        if waiting:
            body += (f" · {len(waiting)} could not be graded — open Submissions and use "
                     "\"Process all pending\" to retry")
        notify(db, exam, "autograde_finished", f"Grading finished — {exam.title}", body,
               link_tab="review" if review else "results")
        logger.info("Auto-grade: exam %d finished (%d graded, %d waiting)", exam.id, len(graded_subs), len(waiting))


def tick() -> None:
    """One scheduler pass. Safe to call directly (tests do)."""
    from database import SessionLocal

    db = SessionLocal()
    try:
        _start_due_exams(db)
        _finish_started_exams(db)
    finally:
        db.close()


async def _loop() -> None:
    await asyncio.sleep(5)
    while True:
        try:
            tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Auto-grade scheduler tick failed")
        await asyncio.sleep(_INTERVAL_S)


async def start_scheduler() -> None:
    """Start the scheduler task. Call once from the FastAPI lifespan."""
    global _task
    _task = asyncio.create_task(_loop(), name="autograde-scheduler")
    logger.info("Auto-grade scheduler started (every %ds).", _INTERVAL_S)
