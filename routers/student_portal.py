"""Student-facing API (/api/v1/student/*).

Students can: redeem an enrollment code, see the activities and exams their
teacher posted (read-only), download their personalised template, and upload
their finished paper. Nothing here edits an exam, and nothing here touches
OCR or grading — the teacher still processes submissions from their own screens.
"""
from __future__ import annotations

import io
import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel
from sqlalchemy.orm import Session

import db_models as m
from api_schemas import UtcDateTime
from autograde import exam_is_closed
from notifications import notify_student_submitted
from auth import check_attempt_limit, record_attempt_fail, require_student
from database import get_db
from identification_scoring import parse_accepted_answers
from routers.api_v1 import DATA_ROOT, _ensure_data_root, download_student_paper

router = APIRouter(prefix="/api/v1/student", tags=["student"], dependencies=[Depends(require_student)])

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
_GRADED_STATUSES = {"graded", "reviewed", "published"}

# Pages can only be added/removed while the paper is a draft. "submitted" means
# the student turned it in (they must unsubmit to change it), and anything later
# (ocr_done, graded, ...) belongs to the teacher's grading pipeline.
_EDITABLE_STATUSES = {"draft"}


def _locked_detail(status: str) -> str:
    if status == "submitted":
        return "You have already submitted this paper. Unsubmit it first to change your pages."
    return "Your paper is already being checked; ask your teacher to change it."


# ── Schemas ──────────────────────────────────────────────────────────────────


class EnrollBody(BaseModel):
    code: str


class StudentClass(BaseModel):
    id: int
    code: str
    name: str


class StudentExam(BaseModel):
    id: int
    class_id: int
    class_name: str
    exam_code: str
    title: str
    description: str | None
    template_ready: bool
    question_count: int
    total_points: float
    teacher_name: str | None
    posted_at: datetime
    due_at: UtcDateTime | None
    overdue: bool                  # past the deadline and not yet submitted
    submitted_late: bool
    results_available: bool        # teacher released results and this paper is graded
    closed: bool                   # auto-grade exam past its deadline: no submit/edit/unsubmit
    submission_status: str  # "not_submitted" | draft | submitted | ocr_done | reviewed | published
    file_count: int


class StudentFile(BaseModel):
    id: int
    page_number: int
    original_filename: str


class StudentSubmission(BaseModel):
    exam_id: int
    status: str
    editable: bool        # pages can be added/removed (draft only)
    can_submit: bool      # draft with at least one page
    can_unsubmit: bool    # submitted by the student and not yet picked up for grading
    closed: bool = False  # the exam is closed to changes (auto-grade deadline passed)
    due_at: UtcDateTime | None
    submitted_at: UtcDateTime | None
    is_late: bool
    files: list[StudentFile]


class StudentProfile(BaseModel):
    id: int
    email: str
    full_name: str
    linked: bool
    student_id: str | None


# ── Helpers ──────────────────────────────────────────────────────────────────


def _student_row(db: Session, acct: m.StudentAccount) -> m.Student:
    if acct.student_id is None:
        raise HTTPException(status_code=403, detail="Enter an enrollment code from your teacher first")
    st = db.get(m.Student, acct.student_id)
    if not st:
        raise HTTPException(status_code=403, detail="Student record not found")
    return st


def _redeemed_class_ids(db: Session, st: m.Student) -> list[int]:
    rows = (
        db.query(m.Enrollment.class_id)
        .filter(m.Enrollment.student_id == st.id, m.Enrollment.redeemed_at.isnot(None))
        .all()
    )
    return [r[0] for r in rows]


def _exam_for_student(db: Session, st: m.Student, exam_id: int) -> m.Exam:
    exam = db.get(m.Exam, exam_id)
    if not exam or exam.class_id not in _redeemed_class_ids(db, st):
        raise HTTPException(status_code=404, detail="Exam not found")
    return exam


def _get_submission(db: Session, st: m.Student, exam: m.Exam) -> m.Submission | None:
    return (
        db.query(m.Submission)
        .filter(m.Submission.exam_id == exam.id, m.Submission.student_id == st.id)
        .first()
    )


def _get_or_create_submission(db: Session, st: m.Student, exam: m.Exam) -> m.Submission:
    sub = _get_submission(db, st, exam)
    if not sub:
        sub = m.Submission(exam_id=exam.id, student_id=st.id, status="draft")
        db.add(sub)
        db.commit()
        db.refresh(sub)
    return sub


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _is_late(exam: m.Exam, sub: m.Submission | None) -> bool:
    """Submitted by the student after the deadline. Papers the teacher uploaded
    on the student's behalf, and older ones with no timestamp, are never late."""
    return bool(
        exam.due_at and sub and sub.submitted_at and sub.uploaded_by == "student"
        and sub.submitted_at > exam.due_at
    )


_CLOSED_MSG = (
    "Submissions for this exam are closed: the deadline has passed and your teacher's "
    "grading is under way. Ask your teacher if you need to submit late."
)


def _submission_view(exam: m.Exam, sub: m.Submission | None) -> StudentSubmission:
    closed = exam_is_closed(exam)
    if not sub:
        return StudentSubmission(
            exam_id=exam.id, status="not_submitted", editable=not closed,
            can_submit=False, can_unsubmit=False, closed=closed,
            due_at=exam.due_at, submitted_at=None, is_late=False, files=[],
        )
    return StudentSubmission(
        exam_id=exam.id,
        due_at=exam.due_at,
        submitted_at=sub.submitted_at,
        is_late=_is_late(exam, sub),
        status=sub.status,
        closed=closed,
        editable=sub.status in _EDITABLE_STATUSES and not closed,
        can_submit=sub.status in _EDITABLE_STATUSES and len(sub.files) > 0 and not closed,
        can_unsubmit=sub.status == "submitted" and sub.uploaded_by != "teacher" and not closed,
        files=[
            StudentFile(id=f.id, page_number=f.page_number, original_filename=f.original_filename)
            for f in sorted(sub.files, key=lambda f: f.page_number)
        ],
    )


# ── Profile + enrollment ─────────────────────────────────────────────────────


@router.get("/profile", response_model=StudentProfile)
def profile(db: Session = Depends(get_db), acct: m.StudentAccount = Depends(require_student)) -> StudentProfile:
    st = db.get(m.Student, acct.student_id) if acct.student_id else None
    return StudentProfile(
        id=acct.id, email=acct.email, full_name=acct.full_name,
        linked=st is not None, student_id=st.student_id if st else None,
    )


@router.post("/enroll", response_model=StudentClass)
def redeem_code(
    body: EnrollBody,
    db: Session = Depends(get_db),
    acct: m.StudentAccount = Depends(require_student),
) -> StudentClass:
    """Join a class with the one-time code the teacher gave this student."""
    limit_key = f"enroll:{acct.id}"
    check_attempt_limit(limit_key)
    code = "".join(ch for ch in body.code.upper() if ch.isalnum())
    en = db.query(m.Enrollment).filter(m.Enrollment.access_code == code).first() if code else None
    if not en:
        record_attempt_fail(limit_key)
        raise HTTPException(status_code=404, detail="Invalid enrollment code")
    if en.redeemed_at is not None:
        record_attempt_fail(limit_key)
        raise HTTPException(status_code=409, detail="This code has already been used")

    if acct.student_id is None:
        # First redemption binds this login to the student record the teacher enrolled.
        taken = db.query(m.StudentAccount).filter(m.StudentAccount.student_id == en.student_id).first()
        if taken:
            record_attempt_fail(limit_key)
            raise HTTPException(status_code=409, detail="This student is already linked to another account")
        acct.student_id = en.student_id
    elif acct.student_id != en.student_id:
        record_attempt_fail(limit_key)
        raise HTTPException(status_code=403, detail="This code was issued to a different student")

    en.redeemed_at = datetime.now(timezone.utc)
    db.commit()
    course = db.get(m.CourseClass, en.class_id)
    return StudentClass(id=course.id, code=course.code, name=course.name)


# ── Read-only dashboard ──────────────────────────────────────────────────────


@router.get("/classes", response_model=list[StudentClass])
def my_classes(db: Session = Depends(get_db), acct: m.StudentAccount = Depends(require_student)) -> list[StudentClass]:
    if acct.student_id is None:
        return []
    st = _student_row(db, acct)
    ids = _redeemed_class_ids(db, st)
    rows = db.query(m.CourseClass).filter(m.CourseClass.id.in_(ids)).order_by(m.CourseClass.code).all() if ids else []
    return [StudentClass(id=c.id, code=c.code, name=c.name) for c in rows]


@router.get("/exams", response_model=list[StudentExam])
def my_exams(db: Session = Depends(get_db), acct: m.StudentAccount = Depends(require_student)) -> list[StudentExam]:
    """Every activity/exam posted in the student's classes, with their own submission status."""
    if acct.student_id is None:
        return []
    st = _student_row(db, acct)
    ids = _redeemed_class_ids(db, st)
    if not ids:
        return []
    exams = db.query(m.Exam).filter(m.Exam.class_id.in_(ids)).order_by(m.Exam.created_at.desc()).all()
    out: list[StudentExam] = []
    teacher_names: dict[int, str] = {}
    for ex in exams:
        sub = _get_submission(db, st, ex)
        tid = ex.course_class.teacher_id
        if tid is not None and tid not in teacher_names:
            t = db.get(m.Teacher, tid)
            teacher_names[tid] = t.full_name if t else ""
        out.append(
            StudentExam(
                id=ex.id,
                class_id=ex.class_id,
                class_name=ex.course_class.name,
                exam_code=ex.exam_code,
                title=ex.title,
                description=ex.description,
                template_ready=bool(ex.template_spec_json),
                question_count=len(ex.questions),
                total_points=sum(q.max_points for q in ex.questions),
                teacher_name=(teacher_names.get(tid) or None) if tid is not None else None,
                posted_at=ex.created_at,
                due_at=ex.due_at,
                overdue=bool(
                    ex.due_at and ex.due_at < _now_utc()
                    and (not sub or sub.status in ("draft", "not_submitted"))
                ),
                submitted_late=_is_late(ex, sub),
                results_available=bool(
                    ex.results_released_at and sub and sub.status in _GRADED_STATUSES
                ),
                closed=exam_is_closed(ex),
                submission_status=sub.status if sub else "not_submitted",
                file_count=len(sub.files) if sub else 0,
            )
        )
    return out


# ── Questions (read-only) ────────────────────────────────────────────────────


class StudentQuestion(BaseModel):
    order_index: int
    prompt: str
    question_type: str            # essay | mcq | tf | identification
    choices: list[str] | None     # MCQ options only
    max_points: float
    # Deliberately absent: correct_answer, rubric_text, rubric_criteria_json,
    # case_sensitive — those are the teacher's grading data.


@router.get("/exams/{exam_id}/questions", response_model=list[StudentQuestion])
def exam_questions(
    exam_id: int,
    db: Session = Depends(get_db),
    acct: m.StudentAccount = Depends(require_student),
) -> list[StudentQuestion]:
    """The questions a teacher posted, once the teacher has published the template."""
    st = _student_row(db, acct)
    exam = _exam_for_student(db, st, exam_id)
    # The template is the teacher's "ready" signal; until then the exam may be half built.
    if not exam.template_spec_json:
        raise HTTPException(status_code=409, detail="Your teacher has not published this exam yet")
    out: list[StudentQuestion] = []
    for q in exam.questions:
        choices = None
        if q.question_type == "mcq" and q.choices_json:
            try:
                parsed = json.loads(q.choices_json)
                choices = [str(c) for c in parsed] if isinstance(parsed, list) else None
            except ValueError:
                choices = None
        out.append(StudentQuestion(
            order_index=q.order_index,
            prompt=q.prompt,
            question_type=q.question_type,
            choices=choices,
            max_points=q.max_points,
        ))
    return out


# ── Results (only after the teacher releases them) ───────────────────────────


class CriterionResult(BaseModel):
    criterion: str
    score: float
    max_points: float


class StudentQuestionResult(BaseModel):
    order_index: int
    prompt: str
    question_type: str
    choices: list[str] | None
    max_points: float
    score: float | None                    # None = no answer was recorded
    criteria: list[CriterionResult] | None  # essays with a structured rubric
    correct_answer: str | None              # every type except essay
    total_adjusted: bool                    # teacher changed the total from the criteria sum
    # Deliberately absent: AI justifications, rubric level descriptions,
    # teacher notes, OCR text and confidence values.


class StudentResults(BaseModel):
    released: bool
    graded: bool
    total_score: float | None
    total_max: float
    questions: list[StudentQuestionResult]


def _display_correct_answer(q: m.ExamQuestion, choices: list[str] | None) -> str | None:
    raw = (q.correct_answer or "").strip()
    if not raw:
        return None
    if q.question_type == "mcq":
        idx = ord(raw[0].upper()) - 65
        if choices and 0 <= idx < len(choices):
            return f"{raw[0].upper()}. {choices[idx]}"
        return raw
    if q.question_type == "identification":
        accepted = parse_accepted_answers(raw)
        return " / ".join(accepted) if accepted else raw
    return raw   # true/false


def _criteria_of(ans: m.SubmissionAnswer) -> list[CriterionResult] | None:
    if not ans.ai_criteria_scores_json:
        return None
    try:
        items = json.loads(ans.ai_criteria_scores_json)
    except ValueError:
        return None
    out: list[CriterionResult] = []
    for it in items if isinstance(items, list) else []:
        try:
            out.append(CriterionResult(
                criterion=str(it.get("criterion", "")),
                score=float(it.get("score", 0) or 0),
                max_points=float(it.get("max_points", 0) or 0),
            ))
        except (TypeError, ValueError, AttributeError):
            continue
    return out or None


@router.get("/exams/{exam_id}/results", response_model=StudentResults)
def exam_results(
    exam_id: int,
    db: Session = Depends(get_db),
    acct: m.StudentAccount = Depends(require_student),
) -> StudentResults:
    """The student's own graded results, once the teacher has released them."""
    st = _student_row(db, acct)
    exam = _exam_for_student(db, st, exam_id)
    total_max = float(sum(q.max_points for q in exam.questions))
    if not exam.results_released_at:
        return StudentResults(released=False, graded=False, total_score=None, total_max=total_max, questions=[])

    sub = _get_submission(db, st, exam)
    if not sub or sub.status not in _GRADED_STATUSES:
        return StudentResults(released=True, graded=False, total_score=None, total_max=total_max, questions=[])

    # One answer per question: the most recent.
    latest: dict[int, m.SubmissionAnswer] = {}
    for a in sorted(sub.answers, key=lambda a: a.id):
        if a.question_id is not None:
            latest[a.question_id] = a

    out: list[StudentQuestionResult] = []
    total = 0.0
    for q in exam.questions:
        choices = None
        if q.question_type == "mcq" and q.choices_json:
            try:
                parsed = json.loads(q.choices_json)
                choices = [str(c) for c in parsed] if isinstance(parsed, list) else None
            except ValueError:
                choices = None

        ans = latest.get(q.id)
        score = None
        criteria = None
        adjusted = False
        if ans is not None:
            score = ans.teacher_score if ans.teacher_score is not None else ans.ai_score
            if q.question_type == "essay":
                criteria = _criteria_of(ans)
                if criteria and ans.teacher_score is not None:
                    adjusted = abs(sum(c.score for c in criteria) - ans.teacher_score) > 0.01
        if score is not None:
            total += float(score)

        out.append(StudentQuestionResult(
            order_index=q.order_index,
            prompt=q.prompt,
            question_type=q.question_type,
            choices=choices,
            max_points=q.max_points,
            score=None if score is None else float(score),
            criteria=criteria,
            correct_answer=None if q.question_type == "essay" else _display_correct_answer(q, choices),
            total_adjusted=adjusted,
        ))

    return StudentResults(released=True, graded=True, total_score=total, total_max=total_max, questions=out)


# ── Template download ────────────────────────────────────────────────────────


@router.get("/exams/{exam_id}/template")
def download_template(
    exam_id: int,
    db: Session = Depends(get_db),
    acct: m.StudentAccount = Depends(require_student),
) -> FileResponse:
    """Personalised paper (carries this student's QR) for the given exam."""
    st = _student_row(db, acct)
    exam = _exam_for_student(db, st, exam_id)
    if not exam.template_spec_json:
        raise HTTPException(status_code=409, detail="Your teacher has not published the template for this exam yet")
    sub = _get_or_create_submission(db, st, exam)
    return download_student_paper(sub.id, db)


# ── Submission upload ────────────────────────────────────────────────────────


@router.get("/exams/{exam_id}/submission", response_model=StudentSubmission)
def my_submission(
    exam_id: int, db: Session = Depends(get_db), acct: m.StudentAccount = Depends(require_student)
) -> StudentSubmission:
    st = _student_row(db, acct)
    exam = _exam_for_student(db, st, exam_id)
    return _submission_view(exam, _get_submission(db, st, exam))


@router.post("/exams/{exam_id}/submission/files", response_model=StudentSubmission)
async def upload_my_file(
    exam_id: int,
    file: UploadFile = File(...),
    page_number: int = Query(default=1, ge=1, le=50),
    db: Session = Depends(get_db),
    acct: m.StudentAccount = Depends(require_student),
) -> StudentSubmission:
    """Upload (or replace) one page of the student's own paper."""
    st = _student_row(db, acct)
    exam = _exam_for_student(db, st, exam_id)
    if exam_is_closed(exam):
        raise HTTPException(status_code=409, detail=_CLOSED_MSG)
    sub = _get_or_create_submission(db, st, exam)
    if sub.status not in _EDITABLE_STATUSES:
        raise HTTPException(status_code=409, detail=_locked_detail(sub.status))

    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (15 MB max)")
    try:
        Image.open(io.BytesIO(raw)).verify()
    except Exception:
        raise HTTPException(status_code=400, detail="That file is not a readable image (use JPG or PNG)")

    _ensure_data_root()
    safe_name = os.path.basename(file.filename or "upload.jpg")
    dest_dir = DATA_ROOT / str(sub.id)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Re-uploading a page replaces it, so a student can fix a bad photo.
    for old in [f for f in sub.files if f.page_number == page_number]:
        try:
            (DATA_ROOT.parent.parent / old.stored_path).unlink(missing_ok=True)
        except OSError:
            pass
        db.delete(old)

    dest_path = dest_dir / f"p{page_number}_{safe_name}"
    dest_path.write_bytes(raw)
    rel = str(dest_path.relative_to(DATA_ROOT.parent.parent)).replace("\\", "/")
    db.add(m.SubmissionFile(
        submission_id=sub.id, page_number=page_number, original_filename=safe_name, stored_path=rel,
    ))
    # Stays a draft: the paper only reaches the teacher once the student submits it.
    sub.uploaded_by = "student"
    db.commit()
    db.refresh(sub)
    return _submission_view(exam, sub)


@router.post("/exams/{exam_id}/submission/submit", response_model=StudentSubmission)
def submit_my_paper(
    exam_id: int,
    db: Session = Depends(get_db),
    acct: m.StudentAccount = Depends(require_student),
) -> StudentSubmission:
    """Finalize the paper: it becomes visible to the teacher as submitted."""
    st = _student_row(db, acct)
    exam = _exam_for_student(db, st, exam_id)
    if exam_is_closed(exam):
        raise HTTPException(status_code=409, detail=_CLOSED_MSG)
    sub = _get_submission(db, st, exam)
    if not sub or not sub.files:
        raise HTTPException(status_code=409, detail="Add at least one page before submitting")
    if sub.status == "submitted":
        return _submission_view(exam, sub)   # idempotent
    if sub.status not in _EDITABLE_STATUSES:
        raise HTTPException(status_code=409, detail=_locked_detail(sub.status))
    sub.status = "submitted"
    sub.uploaded_by = "student"
    sub.submitted_at = _now_utc()   # server clock decides lateness, not the browser
    db.commit()
    db.refresh(sub)
    notify_student_submitted(db, exam, st.full_name, late=_is_late(exam, sub))
    return _submission_view(exam, sub)


@router.post("/exams/{exam_id}/submission/unsubmit", response_model=StudentSubmission)
def unsubmit_my_paper(
    exam_id: int,
    db: Session = Depends(get_db),
    acct: m.StudentAccount = Depends(require_student),
) -> StudentSubmission:
    """Take a submitted paper back to draft so pages can be changed."""
    st = _student_row(db, acct)
    exam = _exam_for_student(db, st, exam_id)
    if exam_is_closed(exam):
        raise HTTPException(status_code=409, detail=_CLOSED_MSG)
    sub = _get_submission(db, st, exam)
    if not sub:
        raise HTTPException(status_code=404, detail="Nothing submitted yet")
    if sub.status in _EDITABLE_STATUSES:
        return _submission_view(exam, sub)   # already a draft
    if sub.status != "submitted":
        raise HTTPException(status_code=409, detail=_locked_detail(sub.status))
    if sub.uploaded_by == "teacher":
        raise HTTPException(status_code=409, detail="Your teacher uploaded this paper, so only they can change it")
    sub.status = "draft"
    sub.submitted_at = None          # resubmitting is timed afresh
    db.commit()
    db.refresh(sub)
    return _submission_view(exam, sub)


@router.delete("/exams/{exam_id}/submission/files/{file_id}", response_model=StudentSubmission)
def delete_my_file(
    exam_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    acct: m.StudentAccount = Depends(require_student),
) -> StudentSubmission:
    st = _student_row(db, acct)
    exam = _exam_for_student(db, st, exam_id)
    if exam_is_closed(exam):
        raise HTTPException(status_code=409, detail=_CLOSED_MSG)
    sub = _get_submission(db, st, exam)
    if not sub:
        raise HTTPException(status_code=404, detail="Nothing submitted yet")
    if sub.status not in _EDITABLE_STATUSES:
        raise HTTPException(status_code=409, detail=_locked_detail(sub.status))
    row = next((f for f in sub.files if f.id == file_id), None)
    if not row:
        raise HTTPException(status_code=404, detail="File not found")
    try:
        (DATA_ROOT.parent.parent / row.stored_path).unlink(missing_ok=True)
    except OSError:
        pass
    db.delete(row)
    db.flush()
    db.refresh(sub)
    if not sub.files:
        sub.status = "draft"
        sub.uploaded_by = None
    db.commit()
    db.refresh(sub)
    return _submission_view(exam, sub)
