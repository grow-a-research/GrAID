from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I lookalikes


def new_access_code() -> str:
    """8-char enrollment code (32^8 space); the column's unique index catches collisions."""
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))


class CourseClass(Base):
    """A class/course section (e.g. CS101-A)."""

    __tablename__ = "course_classes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    # Owning teacher. Nullable: classes created before accounts existed are
    # adopted by the first teacher who registers.
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("teachers.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    enrollments: Mapped[list[Enrollment]] = relationship(back_populates="course_class")
    exams: Mapped[list[Exam]] = relationship(back_populates="course_class")


class Teacher(Base):
    __tablename__ = "teachers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class StudentAccount(Base):
    """Login for a student. Linked to a Student registry row on first code redemption."""

    __tablename__ = "student_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id"), unique=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Notification(Base):
    """In-app notification for a teacher (submissions, grading progress, ...)."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    exam_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # Which tab the notification opens: submissions | results | review
    link_tab: Mapped[str | None] = mapped_column(String(32), nullable=True)
    count: Mapped[int] = mapped_column(Integer, default=1)   # folded duplicates (e.g. 5 submissions)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuthToken(Base):
    """Server-side session token. Only the SHA-256 of the token is stored."""

    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(16))  # "teacher" | "student"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    enrollments: Mapped[list[Enrollment]] = relationship(back_populates="student")
    submissions: Mapped[list[Submission]] = relationship(back_populates="student")


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("class_id", "student_id", name="uq_enrollment_class_student"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("course_classes.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    # One-time code the teacher hands to this student; redeemed in the student portal.
    access_code: Mapped[str | None] = mapped_column(
        String(16), unique=True, index=True, nullable=True, default=new_access_code
    )
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    course_class: Mapped[CourseClass] = relationship(back_populates="enrollments")
    student: Mapped[Student] = relationship(back_populates="enrollments")


class Exam(Base):
    __tablename__ = "exams"
    __table_args__ = (UniqueConstraint("class_id", "exam_code", name="uq_exam_class_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("course_classes.id"), index=True)
    exam_code: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON spec for Phase 4 printable templates (marker positions, answer regions).
    # Nullable — populated once a template is generated; None means free-form scan.
    template_spec_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional deadline (naive UTC). NULL = no deadline.
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # When the teacher released results to students (naive UTC). NULL = not released.
    results_released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Teacher switch: grade submitted papers automatically once the deadline passes.
    # Requires a deadline. When on, students can't submit/edit/unsubmit after it.
    auto_grade: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    auto_grade_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    auto_grade_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    course_class: Mapped[CourseClass] = relationship(back_populates="exams")
    questions: Mapped[list[ExamQuestion]] = relationship(
        back_populates="exam", order_by="ExamQuestion.order_index"
    )
    submissions: Mapped[list[Submission]] = relationship(back_populates="exam")


class ExamQuestion(Base):
    __tablename__ = "exam_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=1)
    prompt: Mapped[str] = mapped_column(Text)
    question_type: Mapped[str] = mapped_column(String(32), default="essay")
    rubric_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Structured rubric — JSON list of criteria, each with name, max_points, and
    # a list of performance levels ({label, points, description}). When set,
    # this takes over from rubric_text for grading and PDF export, and
    # max_points is kept in sync as sum(criteria max_points) server-side.
    rubric_criteria_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_points: Mapped[float] = mapped_column(Float, default=10.0)
    # MCQ choices as JSON list of strings, e.g. ["Paris", "London", "Berlin", "Rome"]
    choices_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Correct answer: letter for MCQ ("A"/"B"/"C"/"D"), "True"/"False" for tf,
    # or, for identification, the teacher's accepted answers separated by "|".
    correct_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Identification only — whether exact-match scoring compares case.
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Bounding-box region on the template page for Phase 5 template-aware cropping.
    # JSON: {"page": 1, "x1": 0, "y1": 0, "x2": 0, "y2": 0}
    # Nullable — populated in Phase 4 when the template is generated.
    region_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    exam: Mapped[Exam] = relationship(back_populates="questions")
    answers: Mapped[list[SubmissionAnswer]] = relationship(back_populates="question")


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("exam_id", "student_id", name="uq_submission_exam_student"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    # Status lifecycle: draft → submitted → ocr_done → reviewed → published
    status: Mapped[str] = mapped_column(String(32), default="draft")
    # Who last uploaded files: "student", "teacher", or NULL (legacy / none yet).
    uploaded_by: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # When the student pressed Submit (naive UTC); NULL if never / legacy.
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    exam: Mapped[Exam] = relationship(back_populates="submissions")
    student: Mapped[Student] = relationship(back_populates="submissions")
    files: Mapped[list[SubmissionFile]] = relationship(back_populates="submission")
    answers: Mapped[list[SubmissionAnswer]] = relationship(back_populates="submission")


class SubmissionFile(Base):
    __tablename__ = "submission_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), index=True)
    page_number: Mapped[int] = mapped_column(Integer, default=1)
    original_filename: Mapped[str] = mapped_column(String(512))
    stored_path: Mapped[str] = mapped_column(String(1024))

    submission: Mapped[Submission] = relationship(back_populates="files")


class SubmissionAnswer(Base):
    """
    Stores OCR + AI grading results per question (Phase 5/6).

    question_id is NULL only for fallback full-page OCR (no template / bad scan).
    """

    __tablename__ = "submission_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), index=True)
    question_id: Mapped[int | None] = mapped_column(
        ForeignKey("exam_questions.id"), nullable=True, index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, default=1)
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON array: [{"x1":0,"y1":0,"x2":0,"y2":0}, ...]
    boxes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Status: pending | ocr_done | graded | error
    status: Mapped[str] = mapped_column(String(32), default="pending")

    # Phase 6 — AI grading (Groq)
    ai_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Structured per-criterion grading breakdown — JSON list of
    # {criterion, max_points, score, justification}. Populated only when the
    # question has a structured rubric (rubric_criteria_json); NULL otherwise.
    ai_criteria_scores_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Suggested performance band (Poor/Fair/Good/Excellent) from the ordinal
    # classification model in band_classifier.py — EXPERIMENTAL, essays with a
    # structured rubric only. Probabilities are a JSON object band -> 0-1;
    # spread is the highest minus lowest criterion percentage.
    ai_band: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ai_band_probs_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_band_model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # OCR quality metrics (populated when reference text is available)
    cer: Mapped[float | None] = mapped_column(Float, nullable=True)
    wer: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Teacher override — final_score = teacher_score if set, else ai_score
    teacher_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    teacher_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Phase 13 — OMR confidence (0–1). Set for MCQ/TF answers processed by the
    # bubble-fill detector. None for essay/identification (OCR path).
    omr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Phase 16 — Groq grading confidence (0–1). Only populated for essay answers.
    groq_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Phase 21 — Laplacian variance of the answer crop (proxy for OCR scan clarity).
    # Higher = sharper / more legible. None for OMR (MCQ/TF) answers.
    ocr_clarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Qwen's lowest line confidence for this answer's transcription (0–1) — the
    # numeric behind the low_confidence flag, persisted so the combined
    # OCR+grading confidence can be recomputed and reported per answer.
    # None on MCQ/TF, and on answers OCR'd by a server build that predates the
    # field (see _run_remote_ocr_pipeline) — None means unknown, never "low".
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Teacher pressed "Mark reviewed" (naive UTC). A review marker only — it never
    # changes status, scores or any grading data.
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    submission: Mapped[Submission] = relationship(back_populates="answers")
    question: Mapped[ExamQuestion | None] = relationship(
        back_populates="answers", foreign_keys=[question_id]
    )
    flag: Mapped[FlagLog | None] = relationship(
        back_populates="answer", uselist=False
    )


class FlagLog(Base):
    """
    Phase 17 — RQ4 flag log.

    One row per SubmissionAnswer that was auto-flagged or manually flagged.
    Tracks whether the professor reviewed it and what they decided, enabling
    Precision / Recall measurement for the auto-flagging system.

    review_decision values:
      confirmed_error  → flag was correct (True Positive)
      false_positive   → flag was wrong, answer was fine (False Positive)
      verified         → professor confirmed an UN-flagged answer is correct (True Negative,
                         stored here when professor clicks "Mark as verified" on an unflagged answer)
    """

    __tablename__ = "flag_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    submission_answer_id: Mapped[int] = mapped_column(
        ForeignKey("submission_answers.id"), unique=True, index=True
    )
    # Reason code: essay_score_zero | essay_low_confidence | omr_low_confidence |
    #              omr_no_detection | identification_no_match |
    #              identification_ocr_unreadable | manual | verified
    flag_reason: Mapped[str] = mapped_column(String(64))
    # Whether this was raised automatically (True) or by the teacher (False/None)
    auto_flagged: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_flagged_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    # Review fields — populated when a teacher acts on the flag
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    review_decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    answer: Mapped[SubmissionAnswer] = relationship(back_populates="flag")
