from __future__ import annotations

import csv
import io
import json
import logging
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import cv2

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from PIL import Image, ImageOps
from sqlalchemy.orm import Session

import db_models as m
from api_schemas import (
    BatchFileResult,
    BatchUploadResult,
    BulkDeleteResult,
    BulkEnrollResult,
    BulkProcessResult,
    BulkProcessStatus,
    ClassAnalytics,
    QueueEnqueueResult,
    QueueStatus,
    CourseClassCreate,
    CourseClassRead,
    EnrollmentCreate,
    EnrollmentRead,
    ExamCreate,
    ExamQuestionCreate,
    ExamQuestionRead,
    ExamQuestionUpdate,
    ExamRead,
    ExamStats,
    FlagCreate,
    FlagLogRead,
    FlagReview,
    FlagStats,
    ImportResult,
    OcrResult,
    QuestionImportResult,
    QuestionStats,
    RubricCriteriaParseResult,
    RubricImportResult,
    StudentAnalytics,
    StudentCreate,
    StudentRead,
    StudentUpdate,
    SubmissionAnswerRead,
    SubmissionCreate,
    SubmissionFileRead,
    SubmissionRead,
    SubmissionStats,
    SubmissionSummary,
    TeacherOverride,
)
from database import get_db

router = APIRouter(prefix="/api/v1", tags=["platform"])

DATA_ROOT = Path(__file__).resolve().parent.parent / "data" / "submissions"

# Exam IDs currently running through bulk_process_submissions. Guards against
# a second bulk-process request for the same exam overlapping the first —
# e.g. the frontend's "process all" button state lives only in that browser
# tab and resets on navigation/remount, and the LAN-shared backend can have
# multiple groupmates hitting it at once, so a frontend-only guard can't
# prevent a duplicate concurrent run re-processing the same submissions.
_BULK_PROCESSING_EXAMS: set[int] = set()


def _ensure_data_root() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------


@router.post("/classes", response_model=CourseClassRead)
def create_class(body: CourseClassCreate, db: Session = Depends(get_db)) -> m.CourseClass:
    existing = db.query(m.CourseClass).filter(m.CourseClass.code == body.code).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Class code already exists: {body.code}")
    row = m.CourseClass(code=body.code.strip(), name=body.name.strip())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/classes", response_model=list[CourseClassRead])
def list_classes(db: Session = Depends(get_db)) -> list[m.CourseClass]:
    return db.query(m.CourseClass).order_by(m.CourseClass.code).all()


@router.get("/classes/{class_id}", response_model=CourseClassRead)
def get_class(class_id: int, db: Session = Depends(get_db)) -> m.CourseClass:
    row = db.get(m.CourseClass, class_id)
    if not row:
        raise HTTPException(status_code=404, detail="Class not found")
    return row


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------


@router.post("/students", response_model=StudentRead)
def create_student(body: StudentCreate, db: Session = Depends(get_db)) -> m.Student:
    existing = db.query(m.Student).filter(m.Student.student_id == body.student_id.strip()).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Student ID already exists: {body.student_id}")
    row = m.Student(
        student_id=body.student_id.strip(),
        full_name=body.full_name.strip(),
        email=body.email.strip() if body.email else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/students", response_model=list[StudentRead])
def list_students(db: Session = Depends(get_db)) -> list[m.Student]:
    return db.query(m.Student).order_by(m.Student.student_id).all()


@router.get("/students/{student_id}", response_model=StudentRead)
def get_student(student_id: str, db: Session = Depends(get_db)) -> m.Student:
    """Look up a student by their external school ID string."""
    row = db.query(m.Student).filter(m.Student.student_id == student_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Student not found: {student_id}")
    return row


@router.patch("/students/{student_id}", response_model=StudentRead)
def update_student(student_id: str, body: StudentUpdate, db: Session = Depends(get_db)) -> m.Student:
    """Update a student's full_name and/or email."""
    row = db.query(m.Student).filter(m.Student.student_id == student_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Student not found: {student_id}")
    if body.full_name is not None:
        row.full_name = body.full_name
    if body.email is not None:
        row.email = body.email
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Enrollments
# ---------------------------------------------------------------------------


@router.post("/classes/{class_id}/enrollments", response_model=EnrollmentRead)
def enroll_student(class_id: int, body: EnrollmentCreate, db: Session = Depends(get_db)) -> m.Enrollment:
    course = db.get(m.CourseClass, class_id)
    if not course:
        raise HTTPException(status_code=404, detail="Class not found")
    student = db.query(m.Student).filter(m.Student.student_id == body.student_id.strip()).first()
    if not student:
        raise HTTPException(status_code=404, detail=f"Student not found: {body.student_id}")
    dup = (
        db.query(m.Enrollment)
        .filter(m.Enrollment.class_id == class_id, m.Enrollment.student_id == student.id)
        .first()
    )
    if dup:
        raise HTTPException(status_code=409, detail="Student already enrolled in this class")
    row = m.Enrollment(class_id=class_id, student_id=student.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/classes/{class_id}/enrollments", response_model=list[StudentRead])
def list_enrolled_students(class_id: int, db: Session = Depends(get_db)) -> list[m.Student]:
    course = db.get(m.CourseClass, class_id)
    if not course:
        raise HTTPException(status_code=404, detail="Class not found")
    return (
        db.query(m.Student)
        .join(m.Enrollment, m.Enrollment.student_id == m.Student.id)
        .filter(m.Enrollment.class_id == class_id)
        .order_by(m.Student.student_id)
        .all()
    )


@router.delete("/classes/{class_id}/enrollments/{student_id}", status_code=204)
def unenroll_student(class_id: int, student_id: str, db: Session = Depends(get_db)) -> None:
    student = db.query(m.Student).filter(m.Student.student_id == student_id.strip()).first()
    if not student:
        raise HTTPException(status_code=404, detail=f"Student not found: {student_id}")
    row = (
        db.query(m.Enrollment)
        .filter(m.Enrollment.class_id == class_id, m.Enrollment.student_id == student.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Student is not enrolled in this class")
    db.delete(row)
    db.commit()


@router.post("/classes/{class_id}/enrollments/bulk", response_model=BulkEnrollResult)
def bulk_enroll_students(
    class_id: int,
    body: dict,
    db: Session = Depends(get_db),
) -> BulkEnrollResult:
    """Enroll multiple students by a list of student_id strings.

    Body: {"student_ids": ["2024-0001", "2024-0002", ...]}
    Skips duplicates silently. Reports unknown IDs as errors.
    """
    course = db.get(m.CourseClass, class_id)
    if not course:
        raise HTTPException(status_code=404, detail="Class not found")
    student_ids: list[str] = body.get("student_ids", [])
    enrolled_count = 0
    skipped_count = 0
    errors: list[str] = []
    for sid in student_ids:
        sid = str(sid).strip()
        if not sid:
            continue
        student = db.query(m.Student).filter(m.Student.student_id == sid).first()
        if not student:
            errors.append(f"Student not found: {sid}")
            continue
        dup = (
            db.query(m.Enrollment)
            .filter(m.Enrollment.class_id == class_id, m.Enrollment.student_id == student.id)
            .first()
        )
        if dup:
            skipped_count += 1
            continue
        db.add(m.Enrollment(class_id=class_id, student_id=student.id))
        enrolled_count += 1
    db.commit()
    return BulkEnrollResult(enrolled=enrolled_count, skipped=skipped_count, errors=errors)


# ---------------------------------------------------------------------------
# Exams
# ---------------------------------------------------------------------------


@router.post("/exams", response_model=ExamRead)
def create_exam(body: ExamCreate, db: Session = Depends(get_db)) -> m.Exam:
    course = db.get(m.CourseClass, body.class_id)
    if not course:
        raise HTTPException(status_code=404, detail="Class not found")
    dup = (
        db.query(m.Exam)
        .filter(m.Exam.class_id == body.class_id, m.Exam.exam_code == body.exam_code.strip())
        .first()
    )
    if dup:
        raise HTTPException(status_code=409, detail="Exam code already exists for this class")
    row = m.Exam(
        class_id=body.class_id,
        exam_code=body.exam_code.strip(),
        title=body.title.strip(),
        description=body.description.strip() if body.description else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/exams", response_model=list[ExamRead])
def list_exams(class_id: int | None = None, db: Session = Depends(get_db)) -> list[m.Exam]:
    q = db.query(m.Exam)
    if class_id is not None:
        q = q.filter(m.Exam.class_id == class_id)
    return q.order_by(m.Exam.created_at.desc()).all()


@router.get("/exams/{exam_id}", response_model=ExamRead)
def get_exam(exam_id: int, db: Session = Depends(get_db)) -> m.Exam:
    row = db.get(m.Exam, exam_id)
    if not row:
        raise HTTPException(status_code=404, detail="Exam not found")
    return row


@router.get("/exams/{exam_id}/submissions", response_model=list[SubmissionSummary])
def list_exam_submissions(exam_id: int, db: Session = Depends(get_db)) -> list[SubmissionSummary]:
    """List all submissions for an exam with student info inlined."""
    exam = db.get(m.Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    subs = db.query(m.Submission).filter(m.Submission.exam_id == exam_id).all()
    result = []
    for sub in subs:
        student = db.get(m.Student, sub.student_id)
        result.append(SubmissionSummary(
            id=sub.id,
            status=sub.status,
            student_id=student.student_id if student else "—",
            student_name=student.full_name if student else "—",
            created_at=sub.created_at,
            updated_at=sub.updated_at,
        ))
    return result


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------


def _normalize_rubric_criteria(criteria: list[dict]) -> list[dict]:
    """
    Recompute each criterion's max_points as the highest of its own levels'
    points. The criterion max is derived, never independently client-set, so
    it can't silently disagree with the levels that actually define it.
    """
    normalized = []
    for c in criteria:
        levels = c.get("levels", []) or []
        level_points = [float(lv.get("points", 0) or 0) for lv in levels]
        normalized.append({**c, "max_points": max(level_points) if level_points else 0.0})
    return normalized


@router.post("/exams/{exam_id}/questions", response_model=ExamQuestionRead)
def add_question(exam_id: int, body: ExamQuestionCreate, db: Session = Depends(get_db)) -> m.ExamQuestion:
    exam = db.get(m.Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    qtype = (body.question_type or "essay").strip()
    if qtype in ("mcq", "tf", "identification") and not (body.correct_answer or "").strip():
        raise HTTPException(
            status_code=422,
            detail=f"correct_answer is required for question type '{qtype}'",
        )
    max_points = body.max_points
    rubric_criteria_json = body.rubric_criteria_json
    if body.rubric_criteria_json:
        try:
            criteria = _normalize_rubric_criteria(json.loads(body.rubric_criteria_json))
            max_points = sum(c["max_points"] for c in criteria)
            rubric_criteria_json = json.dumps(criteria)
        except Exception:
            raise HTTPException(status_code=422, detail="rubric_criteria_json is not valid JSON")
    row = m.ExamQuestion(
        exam_id=exam_id,
        order_index=body.order_index,
        prompt=body.prompt,
        question_type=qtype,
        rubric_text=body.rubric_text,
        rubric_criteria_json=rubric_criteria_json,
        max_points=max_points,
        choices_json=body.choices_json,
        correct_answer=body.correct_answer,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/exams/{exam_id}/questions", response_model=list[ExamQuestionRead])
def list_questions(exam_id: int, db: Session = Depends(get_db)) -> list[m.ExamQuestion]:
    exam = db.get(m.Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    return (
        db.query(m.ExamQuestion)
        .filter(m.ExamQuestion.exam_id == exam_id)
        .order_by(m.ExamQuestion.order_index)
        .all()
    )


@router.patch("/exams/{exam_id}/questions/{question_id}", response_model=ExamQuestionRead)
def update_question(
    exam_id: int,
    question_id: int,
    body: ExamQuestionUpdate,
    db: Session = Depends(get_db),
) -> m.ExamQuestion:
    """
    Partially update a question.

    Structural changes (question_type, choices_json, max_points) invalidate the
    exam template — region_json on the question and template_spec_json on the exam
    are cleared so the teacher is prompted to regenerate before processing scans.
    Non-structural changes (prompt, rubric_text, correct_answer) leave the template intact.
    """
    exam = db.get(m.Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    q = db.get(m.ExamQuestion, question_id)
    if not q or q.exam_id != exam_id:
        raise HTTPException(status_code=404, detail="Question not found")

    structural = False  # tracks whether layout-affecting fields changed

    if body.prompt is not None:
        q.prompt = body.prompt.strip()
    if body.question_type is not None:
        new_type = body.question_type.strip()
        if new_type != (q.question_type or "essay"):
            q.question_type = new_type
            structural = True
    if body.rubric_text is not None:
        q.rubric_text = body.rubric_text.strip() or None
    if body.rubric_criteria_json is not None and body.rubric_criteria_json != q.rubric_criteria_json:
        structural = True
        if body.rubric_criteria_json:
            try:
                criteria = _normalize_rubric_criteria(json.loads(body.rubric_criteria_json))
                q.rubric_criteria_json = json.dumps(criteria)
                q.max_points = sum(c["max_points"] for c in criteria)
            except Exception:
                raise HTTPException(status_code=422, detail="rubric_criteria_json is not valid JSON")
        else:
            q.rubric_criteria_json = None
    if (
        body.max_points is not None
        and body.max_points != q.max_points
        and not (body.rubric_criteria_json is not None and q.rubric_criteria_json)
    ):
        # Ignored when a structured rubric is being set in this same request —
        # max_points is derived from criteria max_points above, not client-supplied.
        q.max_points = body.max_points
        structural = True
    if body.choices_json is not None and body.choices_json != q.choices_json:
        q.choices_json = body.choices_json
        structural = True
    if body.correct_answer is not None:
        q.correct_answer = body.correct_answer.strip() or None
    if body.order_index is not None:
        q.order_index = body.order_index

    # Validate correct_answer after all updates are applied
    final_type = (q.question_type or "essay").strip()
    if final_type in ("mcq", "tf", "identification") and not (q.correct_answer or "").strip():
        raise HTTPException(
            status_code=422,
            detail=f"correct_answer is required for question type '{final_type}'",
        )

    if structural:
        q.region_json = None
        exam.template_spec_json = None
        logger.info(
            "Question %d structural change — template invalidated for exam %d",
            question_id, exam_id,
        )

    db.commit()
    db.refresh(q)
    return q


@router.delete("/exams/{exam_id}/questions/{question_id}", status_code=204)
def delete_question(
    exam_id: int,
    question_id: int,
    db: Session = Depends(get_db),
) -> None:
    """
    Delete a question.  Always invalidates the exam template because the page
    layout changes when a question is removed.
    """
    exam = db.get(m.Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    q = db.get(m.ExamQuestion, question_id)
    if not q or q.exam_id != exam_id:
        raise HTTPException(status_code=404, detail="Question not found")

    exam.template_spec_json = None   # layout changed — must regenerate
    db.delete(q)
    db.commit()


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------


@router.post("/submissions", response_model=SubmissionRead)
def create_or_get_submission(body: SubmissionCreate, db: Session = Depends(get_db)) -> m.Submission:
    exam = db.get(m.Exam, body.exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    # Resolve external student_id string → internal Student row.
    student = db.query(m.Student).filter(m.Student.student_id == body.student_id.strip()).first()
    if not student:
        raise HTTPException(status_code=404, detail=f"Student not found: {body.student_id}")

    enr = (
        db.query(m.Enrollment)
        .filter(
            m.Enrollment.class_id == exam.class_id,
            m.Enrollment.student_id == student.id,
        )
        .first()
    )
    if not enr:
        raise HTTPException(
            status_code=400, detail="Student is not enrolled in the class for this exam"
        )

    existing = (
        db.query(m.Submission)
        .filter(m.Submission.exam_id == body.exam_id, m.Submission.student_id == student.id)
        .first()
    )
    if existing:
        return existing

    row = m.Submission(exam_id=body.exam_id, student_id=student.id, status="draft")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/submissions/{submission_id}", response_model=SubmissionRead)
def get_submission(submission_id: int, db: Session = Depends(get_db)) -> m.Submission:
    row = db.get(m.Submission, submission_id)
    if not row:
        raise HTTPException(status_code=404, detail="Submission not found")
    return row


# ---------------------------------------------------------------------------
# Submission files
# ---------------------------------------------------------------------------


@router.get("/submissions/{submission_id}/files", response_model=list[SubmissionFileRead])
def list_submission_files(submission_id: int, db: Session = Depends(get_db)) -> list[m.SubmissionFile]:
    sub = db.get(m.Submission, submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    return db.query(m.SubmissionFile).filter(m.SubmissionFile.submission_id == submission_id).all()


@router.post("/submissions/{submission_id}/files", response_model=SubmissionFileRead)
async def upload_submission_file(
    submission_id: int,
    file: UploadFile = File(...),
    page_number: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
) -> m.SubmissionFile:
    sub = db.get(m.Submission, submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    _ensure_data_root()
    safe_name = os.path.basename(file.filename or "upload.bin")
    dest_dir = DATA_ROOT / str(submission_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"p{page_number}_{safe_name}"
    with dest_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    rel = str(dest_path.relative_to(Path(__file__).resolve().parent.parent))
    row = m.SubmissionFile(
        submission_id=submission_id,
        page_number=page_number,
        original_filename=safe_name,
        stored_path=rel.replace("\\", "/"),
    )
    db.add(row)
    sub.status = "submitted"
    db.commit()
    db.refresh(row)
    return row


@router.delete("/submissions/{submission_id}/files/{file_id}", status_code=204)
def delete_submission_file(
    submission_id: int, file_id: int, db: Session = Depends(get_db)
) -> None:
    row = (
        db.query(m.SubmissionFile)
        .filter(
            m.SubmissionFile.id == file_id,
            m.SubmissionFile.submission_id == submission_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="File not found")
    abs_path = Path(__file__).resolve().parent.parent / row.stored_path
    try:
        abs_path.unlink(missing_ok=True)
    except OSError:
        pass

    # Clean up any OCR/grading results already produced from this page —
    # otherwise a stale SubmissionAnswer (and its flag) outlives the file it
    # came from and keeps showing up / getting re-graded after "deletion".
    stale_answers = (
        db.query(m.SubmissionAnswer)
        .filter(
            m.SubmissionAnswer.submission_id == submission_id,
            m.SubmissionAnswer.page_number == row.page_number,
        )
        .all()
    )
    for ans in stale_answers:
        if ans.flag:
            db.delete(ans.flag)
        db.delete(ans)

    db.delete(row)
    db.commit()


# ---------------------------------------------------------------------------
# OCR — run pipeline on all uploaded files for a submission
# ---------------------------------------------------------------------------


@router.post("/submissions/{submission_id}/ocr", response_model=OcrResult)
def run_submission_ocr(
    submission_id: int,
    db: Session = Depends(get_db),
) -> OcrResult:
    """
    Phase 5 OCR pipeline — template-aware per-question extraction.

    For each uploaded page:
      1. If the exam has a template spec, attempt ArUco marker detection and
         perspective correction, then crop + OCR each answer region individually
         (one SubmissionAnswer per question with question_id populated).
      2. If the exam has no template, or marker detection fails (poor scan),
         fall back to full-page OCR (question_id=None) with a warning logged.

    Updates submission.status → 'ocr_done' when complete.
    """
    import ocr_pipeline
    from ai_grader import correct_id_text, correct_ocr_text
    from job_queue import _laplacian_var as _crop_clarity
    from ocr_alignment import (
        check_scan_quality,
        crop_content_area,
        crop_region,
        detect_and_warp,
    )

    sub = db.get(m.Submission, submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")

    exam = db.get(m.Exam, sub.exam_id)
    template_spec = json.loads(exam.template_spec_json) if exam.template_spec_json else None

    # Pre-load questions with regions only when we have a template
    questions: list[m.ExamQuestion] = []
    if template_spec:
        questions = (
            db.query(m.ExamQuestion)
            .filter(m.ExamQuestion.exam_id == exam.id)
            .order_by(m.ExamQuestion.order_index)
            .all()
        )

    # OCR models are only needed if there are essay/identification questions
    # or no template (fallback full-page OCR path). Pure MCQ/TF exams can run
    # without models via the OMR engine — respect SKIP_MODEL_LOAD=1.
    has_non_omr = (not template_spec) or any(
        (q.question_type or "essay") not in ("mcq", "tf") for q in questions
    )
    if has_non_omr and ocr_pipeline.MODELS is None:
        raise HTTPException(status_code=503, detail="Models not loaded yet")

    files = (
        db.query(m.SubmissionFile)
        .filter(m.SubmissionFile.submission_id == submission_id)
        .order_by(m.SubmissionFile.page_number)
        .all()
    )
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded for this submission")

    project_root = Path(__file__).resolve().parent.parent
    dest_dir = DATA_ROOT / str(submission_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    results: list[m.SubmissionAnswer] = []
    quality_warnings: list[str] = []

    for sf in files:
        img_path = project_root / sf.stored_path
        try:
            # exif_transpose: apply the phone photo's EXIF rotation before any
            # processing, or ArUco alignment maps to the wrong physical
            # corners once markers ARE detected (detection itself doesn't
            # care about orientation, but the resulting warp does).
            image = ImageOps.exif_transpose(Image.open(img_path)).convert("RGB")
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Could not open page {sf.page_number}: {e}"
            ) from e

        # Phase 19: blur / quality pre-check before OCR
        lap_var, is_blurry = check_scan_quality(image)
        if is_blurry:
            msg = (
                f"Page {sf.page_number}: scan appears blurry or low-contrast "
                f"(sharpness score {lap_var:.0f} — retake for best results)."
            )
            quality_warnings.append(msg)
            logger.warning("Quality check — %s", msg)

        now = datetime.now(timezone.utc)
        aligned = False

        # ── Template-aware path ───────────────────────────────────────────────
        if template_spec:
            warped, aligned = detect_and_warp(image, template_spec)

            if aligned:
                # Save perspective-corrected scan for display in Results page
                aligned_path = dest_dir / f"aligned_p{sf.page_number}.png"
                try:
                    warped.save(str(aligned_path))
                    logger.info("Saved aligned image: %s", aligned_path)
                except Exception as e:
                    logger.warning("Could not save aligned image: %s", e)

                for q in questions:
                    if not q.region_json:
                        continue
                    region = json.loads(q.region_json)
                    qtype = (q.question_type or "essay")
                    omr_confidence: float | None = None

                    if qtype in ("mcq", "tf") and region.get("bubbles"):
                        # ── Phase 13: OMR bubble-fill detection ───────────────
                        from omr_engine import (
                            LOW_CONFIDENCE_THRESHOLD,
                            detect_omr,
                        )
                        label, conf, _ = detect_omr(warped, region, template_spec)
                        ocr_text   = label or ""
                        boxes_data = "[]"
                        omr_confidence = conf if label else None
                        # Flag low-confidence or missing detections for review
                        if not ocr_text or (
                            omr_confidence is not None
                            and omr_confidence < LOW_CONFIDENCE_THRESHOLD
                        ):
                            ans_status = "needs_review"
                        else:
                            ans_status = "done"
                        logger.info(
                            "OMR q%d: detected=%r conf=%.2f status=%s",
                            q.order_index, ocr_text, conf, ans_status,
                        )
                    else:
                        # ── OCR path (essay / identification / no bubbles) ────
                        crop = crop_region(warped, region, template_spec)
                        ocr_clarity_val: float | None = _crop_clarity(crop)
                        ocr_text, boxes, _ = ocr_pipeline.run_ocr_pipeline(crop)
                        # MCQ/TF without bubbles: skip Groq correction (answer is
                        # a single letter/word — correction may mangle it)
                        if qtype == "essay":
                            ocr_text = correct_ocr_text(ocr_text)
                        elif qtype == "identification":
                            ocr_text = correct_id_text(ocr_text)
                        boxes_data = json.dumps(
                            [{"x1": b[0], "y1": b[1], "x2": b[2], "y2": b[3]} for b in boxes]
                        )
                        ans_status = "done"

                    existing = (
                        db.query(m.SubmissionAnswer)
                        .filter(
                            m.SubmissionAnswer.submission_id == submission_id,
                            m.SubmissionAnswer.question_id == q.id,
                        )
                        .first()
                    )
                    if existing:
                        existing.ocr_text       = ocr_text
                        existing.boxes_json     = boxes_data
                        existing.status         = ans_status
                        existing.omr_confidence = omr_confidence
                        existing.ocr_clarity    = ocr_clarity_val if qtype not in ("mcq", "tf") else None
                        existing.updated_at     = now
                        db.commit()
                        db.refresh(existing)
                        results.append(existing)
                    else:
                        answer = m.SubmissionAnswer(
                            submission_id=submission_id,
                            question_id=q.id,
                            page_number=sf.page_number,
                            ocr_text=ocr_text,
                            boxes_json=boxes_data,
                            status=ans_status,
                            omr_confidence=omr_confidence,
                            ocr_clarity=ocr_clarity_val if qtype not in ("mcq", "tf") else None,
                        )
                        db.add(answer)
                        db.commit()
                        db.refresh(answer)
                        results.append(answer)

        # ── Fallback: content-area OCR (excludes header + question prompts) ────
        if not aligned:
            fallback_image  = crop_content_area(image, template_spec)
            fallback_clarity = _crop_clarity(fallback_image)
            ocr_text, boxes, _ = ocr_pipeline.run_ocr_pipeline(fallback_image)
            ocr_text = correct_ocr_text(ocr_text)
            boxes_data = json.dumps(
                [{"x1": b[0], "y1": b[1], "x2": b[2], "y2": b[3]} for b in boxes]
            )
            existing = (
                db.query(m.SubmissionAnswer)
                .filter(
                    m.SubmissionAnswer.submission_id == submission_id,
                    m.SubmissionAnswer.page_number == sf.page_number,
                    m.SubmissionAnswer.question_id.is_(None),
                )
                .first()
            )
            if existing:
                existing.ocr_text    = ocr_text
                existing.boxes_json  = boxes_data
                existing.status      = "done"
                existing.ocr_clarity = fallback_clarity
                existing.updated_at  = now
                db.commit()
                db.refresh(existing)
                results.append(existing)
            else:
                answer = m.SubmissionAnswer(
                    submission_id=submission_id,
                    question_id=None,
                    page_number=sf.page_number,
                    ocr_text=ocr_text,
                    boxes_json=boxes_data,
                    status="done",
                    ocr_clarity=fallback_clarity,
                )
                db.add(answer)
                db.commit()
                db.refresh(answer)
                results.append(answer)

    sub.status = "ocr_done"
    db.commit()
    return OcrResult(answers=results, quality_warnings=quality_warnings)


# ---------------------------------------------------------------------------
# Aligned scan image (saved during OCR when ArUco alignment succeeds)
# ---------------------------------------------------------------------------


@router.get("/submissions/{submission_id}/original-image/{page}")
def get_original_image(
    submission_id: int,
    page: int,
    db: Session = Depends(get_db),
) -> FileResponse:
    """
    Return the original uploaded scan for a given page (before any alignment).
    Reads from the SubmissionFile record stored_path.
    """
    sub = db.get(m.Submission, submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    sf = (
        db.query(m.SubmissionFile)
        .filter(
            m.SubmissionFile.submission_id == submission_id,
            m.SubmissionFile.page_number == page,
        )
        .first()
    )
    if not sf:
        raise HTTPException(status_code=404, detail="No file uploaded for this page")
    path = Path(__file__).resolve().parent.parent / sf.stored_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    # Determine media type from extension
    ext = path.suffix.lower()
    media_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }.get(ext, "application/octet-stream")
    return FileResponse(path=str(path), media_type=media_type)


@router.get("/submissions/{submission_id}/aligned-image/{page}")
def get_aligned_image(
    submission_id: int,
    page: int,
    db: Session = Depends(get_db),
) -> FileResponse:
    """
    Return the perspective-corrected (warped) scan image for a given page.
    Saved to data/submissions/{id}/aligned_p{page}.png during OCR.
    Returns 404 if alignment was not possible for that page.
    """
    sub = db.get(m.Submission, submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    path = DATA_ROOT / str(submission_id) / f"aligned_p{page}.png"
    if not path.exists():
        raise HTTPException(
            status_code=404, detail="Aligned image not available for this page"
        )
    return FileResponse(path=str(path), media_type="image/png")


# ---------------------------------------------------------------------------
# Submission answers (read-only — written by the OCR endpoint)
# ---------------------------------------------------------------------------


@router.get("/submissions/{submission_id}/answers", response_model=list[SubmissionAnswerRead])
def list_submission_answers(
    submission_id: int, db: Session = Depends(get_db)
) -> list[m.SubmissionAnswer]:
    sub = db.get(m.Submission, submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    return (
        db.query(m.SubmissionAnswer)
        .filter(m.SubmissionAnswer.submission_id == submission_id)
        .order_by(m.SubmissionAnswer.page_number)
        .all()
    )


# ---------------------------------------------------------------------------
# Phase 4 — Exam template + student paper generation
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "data" / "templates"
_PAPERS_DIR    = Path(__file__).resolve().parent.parent / "data" / "papers"


def _template_pdf_path(exam_id: int) -> Path:
    return _TEMPLATES_DIR / f"exam_{exam_id}_template.pdf"


@router.post("/exams/{exam_id}/template", response_model=ExamRead)
def generate_template(exam_id: int, db: Session = Depends(get_db)) -> m.Exam:
    """
    Generate the printable blank template for an exam.

    - Renders an A4 PDF with ArUco corner markers, a QR code, and one
      ruled answer box per question.
    - Stores the PDF at data/templates/exam_{id}_template.pdf.
    - Writes the template spec (all positions in mm) to
      Exam.template_spec_json and each ExamQuestion.region_json.
    """
    from pdf_generator import QuestionInput, generate_exam_paper

    exam = db.get(m.Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    questions = (
        db.query(m.ExamQuestion)
        .filter(m.ExamQuestion.exam_id == exam_id)
        .order_by(m.ExamQuestion.order_index)
        .all()
    )
    if not questions:
        raise HTTPException(
            status_code=400,
            detail="Exam has no questions. Add questions before generating a template.",
        )

    course = db.get(m.CourseClass, exam.class_id)
    class_code = course.code if course else "—"

    q_inputs = [
        QuestionInput(id=q.id, order_index=q.order_index, prompt=q.prompt, question_type=q.question_type or "essay", choices_json=q.choices_json)
        for q in questions
    ]

    pdf_bytes, template_spec = generate_exam_paper(
        exam_id=exam.id,
        exam_code=exam.exam_code,
        exam_title=exam.title,
        class_code=class_code,
        questions=q_inputs,
    )

    # Persist PDF to disk
    _TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    _template_pdf_path(exam_id).write_bytes(pdf_bytes)

    # Store spec on the exam row
    exam.template_spec_json = json.dumps(template_spec)

    # Store each question's answer-region bounding box + bubble positions (Phase 13)
    for q_spec in template_spec["questions"]:
        q = db.get(m.ExamQuestion, q_spec["question_id"])
        if q:
            q.region_json = json.dumps({
                "page": q_spec["page"],
                "x1_mm": q_spec["x1_mm"],
                "y1_mm": q_spec["y1_mm"],
                "x2_mm": q_spec["x2_mm"],
                "y2_mm": q_spec["y2_mm"],
                "question_type": q_spec.get("question_type", "essay"),
                "bubbles": q_spec.get("bubbles", []),
            })

    db.commit()
    db.refresh(exam)
    return exam


@router.get("/exams/{exam_id}/template/pdf")
def download_template_pdf(exam_id: int, db: Session = Depends(get_db)) -> FileResponse:
    """Download the blank template PDF for printing."""
    exam = db.get(m.Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    if not exam.template_spec_json:
        raise HTTPException(
            status_code=400,
            detail="Template not generated yet. Call POST /api/v1/exams/{id}/template first.",
        )
    path = _template_pdf_path(exam_id)
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Template PDF file missing. Regenerate it via POST /api/v1/exams/{id}/template.",
        )
    return FileResponse(
        path=str(path),
        media_type="application/pdf",
        filename=f"exam_{exam.exam_code}_template.pdf",
    )


@router.get("/exams/{exam_id}/questionnaire/pdf")
def download_questionnaire_pdf(exam_id: int, db: Session = Depends(get_db)) -> Response:
    """
    Download a plain reading document listing each question's prompt (and MCQ
    choices) — separate from the answer-sheet template. Generated fresh from
    current question data on every request; independent of template generation
    (no ArUco/QR, never scanned back, so it doesn't need region_json).
    """
    from pdf_generator import QuestionInput, generate_questionnaire

    exam = db.get(m.Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    questions = (
        db.query(m.ExamQuestion)
        .filter(m.ExamQuestion.exam_id == exam_id)
        .order_by(m.ExamQuestion.order_index)
        .all()
    )
    if not questions:
        raise HTTPException(status_code=400, detail="Exam has no questions.")

    course = db.get(m.CourseClass, exam.class_id)
    class_code = course.code if course else "—"

    q_inputs = [
        QuestionInput(
            id=q.id, order_index=q.order_index, prompt=q.prompt,
            question_type=q.question_type or "essay", choices_json=q.choices_json,
        )
        for q in questions
    ]
    pdf_bytes = generate_questionnaire(
        exam_title=exam.title, exam_code=exam.exam_code,
        class_code=class_code, questions=q_inputs,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="exam_{exam.exam_code}_questionnaire.pdf"'
        },
    )


@router.get("/exams/{exam_id}/rubric/pdf")
def download_rubric_pdf(exam_id: int, db: Session = Depends(get_db)) -> Response:
    """
    Download a single PDF listing every essay question's structured rubric
    (criteria x performance levels) for the exam. Generated fresh from
    current data on every request, like the questionnaire PDF.

    Essay questions that only have a legacy free-text rubric_text (no
    structured rubric_criteria_json) are skipped — there's no tabular
    structure to render for those in v1.
    """
    from pdf_generator import RubricQuestionInput, generate_rubric_pdf

    exam = db.get(m.Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    questions = (
        db.query(m.ExamQuestion)
        .filter(m.ExamQuestion.exam_id == exam_id, m.ExamQuestion.question_type == "essay")
        .order_by(m.ExamQuestion.order_index)
        .all()
    )
    essay_with_criteria = [q for q in questions if q.rubric_criteria_json]
    if not essay_with_criteria:
        raise HTTPException(
            status_code=400,
            detail="No essay questions with a structured rubric found.",
        )

    course = db.get(m.CourseClass, exam.class_id)
    class_code = course.code if course else "—"

    q_inputs = [
        RubricQuestionInput(
            order_index=q.order_index, prompt=q.prompt,
            criteria=json.loads(q.rubric_criteria_json),
        )
        for q in essay_with_criteria
    ]
    pdf_bytes = generate_rubric_pdf(
        exam_title=exam.title, exam_code=exam.exam_code,
        class_code=class_code, questions=q_inputs,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="exam_{exam.exam_code}_rubric.pdf"'
        },
    )


@router.get("/exams/{exam_id}/papers/zip")
def download_all_papers_zip(exam_id: int, db: Session = Depends(get_db)) -> StreamingResponse:
    """
    Generate personalised PDFs for every enrolled student and return them as a ZIP.

    Each file inside the ZIP is named:
        {exam_code}_{student_id}.pdf

    Requires that the exam template has already been generated.
    """
    from pdf_generator import QuestionInput, generate_exam_paper

    exam = db.get(m.Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    if not exam.template_spec_json:
        raise HTTPException(
            status_code=400,
            detail="Exam template not generated yet. Call POST /api/v1/exams/{id}/template first.",
        )

    course = db.get(m.CourseClass, exam.class_id)
    questions = (
        db.query(m.ExamQuestion)
        .filter(m.ExamQuestion.exam_id == exam_id)
        .order_by(m.ExamQuestion.order_index)
        .all()
    )
    if not questions:
        raise HTTPException(status_code=400, detail="Exam has no questions.")

    q_inputs = [
        QuestionInput(id=q.id, order_index=q.order_index, prompt=q.prompt, question_type=q.question_type or "essay", choices_json=q.choices_json)
        for q in questions
    ]

    # Fetch all enrolled students
    enrolled_students: list[m.Student] = (
        db.query(m.Student)
        .join(m.Enrollment, m.Enrollment.student_id == m.Student.id)
        .filter(m.Enrollment.class_id == exam.class_id)
        .order_by(m.Student.student_id)
        .all()
    )
    if not enrolled_students:
        raise HTTPException(status_code=400, detail="No students enrolled in this class.")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for student in enrolled_students:
            pdf_bytes, _ = generate_exam_paper(
                exam_id=exam.id,
                exam_code=exam.exam_code,
                exam_title=exam.title,
                class_code=course.code if course else "—",
                questions=q_inputs,
                student_id=student.student_id,
                student_name=student.full_name,
            )
            filename = f"{exam.exam_code}_{student.student_id}.pdf"
            zf.writestr(filename, pdf_bytes)

    buf.seek(0)
    zip_filename = f"{exam.exam_code}_papers.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )


@router.get("/submissions/{submission_id}/paper")
def download_student_paper(submission_id: int, db: Session = Depends(get_db)) -> FileResponse:
    """
    Return a personalised exam paper PDF for a student.

    The PDF is generated once and cached at data/papers/submission_{id}.pdf.
    The QR code encodes exam_id + student_id for Phase 5 scan identification.
    Requires that the exam template has already been generated.
    """
    from pdf_generator import QuestionInput, generate_exam_paper

    sub = db.get(m.Submission, submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")

    exam    = db.get(m.Exam,        sub.exam_id)
    student = db.get(m.Student,     sub.student_id)
    course  = db.get(m.CourseClass, exam.class_id)

    if not exam.template_spec_json:
        raise HTTPException(
            status_code=400,
            detail="Exam template not generated yet. Call POST /api/v1/exams/{id}/template first.",
        )

    _PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    cached_path = _PAPERS_DIR / f"submission_{submission_id}.pdf"
    filename    = f"exam_{exam.exam_code}_{student.student_id if student else submission_id}.pdf"

    if not cached_path.exists():
        questions = (
            db.query(m.ExamQuestion)
            .filter(m.ExamQuestion.exam_id == exam.id)
            .order_by(m.ExamQuestion.order_index)
            .all()
        )
        q_inputs = [
            QuestionInput(id=q.id, order_index=q.order_index, prompt=q.prompt, question_type=q.question_type or "essay", choices_json=q.choices_json)
            for q in questions
        ]
        pdf_bytes, _ = generate_exam_paper(
            exam_id=exam.id,
            exam_code=exam.exam_code,
            exam_title=exam.title,
            class_code=course.code if course else "—",
            questions=q_inputs,
            student_id=student.student_id if student else None,
            student_name=student.full_name if student else None,
        )
        cached_path.write_bytes(pdf_bytes)

    return FileResponse(
        path=str(cached_path),
        media_type="application/pdf",
        filename=filename,
    )


# ---------------------------------------------------------------------------
# Phase 6 — AI grading (Groq) + teacher override
# ---------------------------------------------------------------------------


def _auto_flag(
    ans: m.SubmissionAnswer,
    reason: str,
    db: Session,
) -> None:
    """
    Create or update a FlagLog row for an answer.
    Idempotent — if a flag already exists the reason is updated but
    any existing review decision is preserved.
    """
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


@router.post("/submissions/{submission_id}/grade", response_model=list[SubmissionAnswerRead])
def grade_submission(
    submission_id: int,
    fuzzy_full: float = Query(default=0.85, ge=0.0, le=1.0,
        description="Minimum fuzzy ratio for full credit on identification questions"),
    fuzzy_partial: float = Query(default=0.60, ge=0.0, le=1.0,
        description="Minimum fuzzy ratio for 50% partial credit on identification questions"),
    db: Session = Depends(get_db),
) -> list[m.SubmissionAnswer]:
    """
    Run AI grading on all OCR'd answers for a submission.

    - Requires GROQ_API_KEY env var.
    - Only grades answers that have ocr_text (skips empty/failed OCR).
    - For answers linked to a question, uses that question's rubric + max_points.
    - Stores ai_score, ai_feedback, and groq_confidence on each SubmissionAnswer.
    - Updates submission.status → 'graded'.
    - fuzzy_full / fuzzy_partial control Identification scoring thresholds.
    """
    from ai_grader import EssayGradeResult, grade_essay
    from omr_engine import MULTIPLE_MARKS_LABEL

    sub = db.get(m.Submission, submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")

    answers = (
        db.query(m.SubmissionAnswer)
        .filter(m.SubmissionAnswer.submission_id == submission_id)
        .order_by(m.SubmissionAnswer.page_number)
        .all()
    )
    if not answers:
        raise HTTPException(
            status_code=400,
            detail="No OCR results found. Run OCR first via POST /submissions/{id}/ocr.",
        )

    exam = db.get(m.Exam, sub.exam_id)
    now  = datetime.now(timezone.utc)

    # Fallback full-page OCR (question_id=None, from a failed alignment) can
    # only be safely graded against a real question when the exam has
    # exactly one non-MCQ/TF question — otherwise there's no way to know
    # which question the full-page text is actually answering. Grading it
    # against generic placeholders (wrong rubric, wrong max_points) instead
    # of leaving it ambiguous silently produces a wrong score, so resolve it
    # once here rather than defaulting blindly per-answer.
    exam_questions = (
        db.query(m.ExamQuestion).filter(m.ExamQuestion.exam_id == exam.id).all()
        if exam else []
    )
    gradable_questions = [
        q for q in exam_questions if (q.question_type or "essay") not in ("mcq", "tf")
    ]
    fallback_question = gradable_questions[0] if len(gradable_questions) == 1 else None

    for ans in answers:
        if not ans.ocr_text:
            continue

        question = (
            db.get(m.ExamQuestion, ans.question_id) if ans.question_id else fallback_question
        )
        qtype = (question.question_type if question else "essay") or "essay"

        if qtype == "essay":
            # --- AI grading via Groq ---
            try:
                result: EssayGradeResult = grade_essay(
                    question_prompt=         question.prompt                if question else "General answer",
                    rubric_text=             question.rubric_text           if question else "Grade for content and clarity.",
                    rubric_criteria_json=    question.rubric_criteria_json  if question else None,
                    max_points=              question.max_points           if question else 10.0,
                    ocr_text=                ans.ocr_text,
                )
                ans.ai_score               = result.score
                ans.ai_feedback            = result.feedback
                ans.groq_confidence        = result.confidence
                ans.ai_criteria_scores_json = result.criteria_scores_json
                ans.status                 = "graded"
                if result.score == 0.0:
                    _auto_flag(ans, "essay_score_zero", db)
                elif result.confidence < 0.4:
                    _auto_flag(ans, "essay_low_confidence", db)
                # Fallback OCR that couldn't be matched to a single real
                # question was graded against generic placeholders above —
                # flag it so the teacher knows this score isn't against the
                # real rubric, instead of it silently looking like a normal grade.
                if ans.question_id is None and question is None:
                    ans.status = "needs_review"
                    _auto_flag(ans, "fallback_ocr_ambiguous_question", db)
            except Exception as e:
                logger.error("Grading failed for answer %d: %s", ans.id, e)
                ans.ai_feedback = f"[Grading error: {e}]"
                ans.status      = "error"

        elif qtype in ("mcq", "tf"):
            # --- Deterministic exact-match scoring (OMR or OCR detected letter) ---
            max_pts = question.max_points if question else 1.0
            if ans.ocr_text.strip() == MULTIPLE_MARKS_LABEL:
                # Two or more bubbles were filled — an invalid answer on any
                # real answer sheet, regardless of which mark is darkest.
                # Score it wrong outright instead of picking a "winner".
                ans.ai_score    = 0.0
                ans.ai_feedback = (
                    f"Correct answer: {question.correct_answer}. "
                    "Detected answer: multiple bubbles marked. "
                    "Incorrect — more than one option was filled in, so no single "
                    "answer can be credited. ⚠ Please verify on the original scan."
                )
                ans.status = "needs_review"
                _auto_flag(ans, "omr_multiple_marks", db)
                continue
            correct = (question.correct_answer or "").strip().upper()
            given   = ans.ocr_text.strip().upper()
            # Accept first letter/word in case noise was picked up
            given_first = given.split()[0] if given else ""
            match = (given_first == correct) or (given == correct)
            ans.ai_score = max_pts if match else 0.0
            feedback = (
                f"Correct answer: {question.correct_answer}. "
                f"Detected answer: {ans.ocr_text.strip() or '(none)'}. "
                + ("Correct." if match else "Incorrect.")
            )
            # Warn on low OMR confidence so the teacher knows to double-check
            if ans.omr_confidence is not None and ans.omr_confidence < 0.30:
                feedback += (
                    f" ⚠ Low OMR confidence ({ans.omr_confidence:.0%})"
                    " — please verify on the original scan."
                )
                ans.status = "needs_review"
                _auto_flag(ans, "omr_low_confidence", db)
            elif not ans.ocr_text.strip():
                feedback += " ⚠ No answer detected — please review."
                ans.status = "needs_review"
                _auto_flag(ans, "omr_no_detection", db)
            else:
                ans.status = "graded"
            ans.ai_feedback = feedback

        elif qtype == "identification":
            # --- Regex / fuzzy match scoring ---
            correct = (question.correct_answer or "").strip()
            given   = ans.ocr_text.strip()
            max_pts = question.max_points if question else 1.0
            # Exact match (case-insensitive)
            if correct.lower() == given.lower():
                score = max_pts
                verdict = "Exact match."
            else:
                # Fuzzy ratio: proportion of matching characters
                import difflib
                ratio = difflib.SequenceMatcher(None, correct.lower(), given.lower()).ratio()
                if ratio >= fuzzy_full:
                    score = max_pts
                    verdict = f"Accepted (fuzzy match {ratio:.0%})."
                elif ratio >= fuzzy_partial:
                    score = max_pts * 0.5
                    verdict = f"Partial credit (fuzzy match {ratio:.0%})."
                else:
                    score = 0.0
                    verdict = f"Incorrect (fuzzy match {ratio:.0%})."
            ans.ai_score    = score
            ans.ai_feedback = (
                f"Expected: {correct}. Your answer: {given}. {verdict}"
            )
            ans.status = "graded"
            if score == 0.0:
                _auto_flag(ans, "identification_no_match", db)

        ans.updated_at = now

    sub.status = "graded"
    db.commit()

    return (
        db.query(m.SubmissionAnswer)
        .filter(m.SubmissionAnswer.submission_id == submission_id)
        .order_by(m.SubmissionAnswer.page_number)
        .all()
    )


@router.post("/exams/{exam_id}/submissions/process-all", response_model=BulkProcessResult)
def bulk_process_submissions(
    exam_id: int,
    db: Session = Depends(get_db),
) -> BulkProcessResult:
    """
    Phase 20: Run OCR + AI grading for every 'submitted' submission in an exam.

    Processes submissions sequentially; errors on individual submissions are
    captured per-entry and do not abort the whole batch. Each submission gets
    its own short-lived database session opened inside the loop, instead of
    holding the request's one injected session for the whole batch — a batch
    of several submissions can take minutes (remote OCR + Groq grading per
    submission), and holding a single pooled connection that long starves
    every other concurrent request (results pages, single-submission
    processing) of connections from the same small pool.
    Uses default fuzzy thresholds (full=0.85, partial=0.60) for Identification.
    """
    if exam_id in _BULK_PROCESSING_EXAMS:
        raise HTTPException(
            status_code=409,
            detail="Bulk processing is already running for this exam — wait for it to finish.",
        )
    _BULK_PROCESSING_EXAMS.add(exam_id)
    try:
        return _run_bulk_process(exam_id, db)
    finally:
        _BULK_PROCESSING_EXAMS.discard(exam_id)


@router.get("/exams/{exam_id}/submissions/process-all/status", response_model=BulkProcessStatus)
def bulk_process_status(exam_id: int) -> BulkProcessStatus:
    """Lets the frontend check whether a bulk-process batch is currently
    running for this exam — from ANY browser tab/session, not just the one
    that started it — so a loading indicator survives navigation/remount
    instead of relying on local component state."""
    return BulkProcessStatus(processing=exam_id in _BULK_PROCESSING_EXAMS)


def _run_bulk_process(exam_id: int, db: Session) -> BulkProcessResult:
    import difflib

    import ocr_pipeline
    from ai_grader import EssayGradeResult, correct_id_text, correct_ocr_text, grade_essay
    from database import SessionLocal
    from ocr_alignment import crop_content_area, crop_region, detect_and_warp
    from omr_engine import LOW_CONFIDENCE_THRESHOLD, MULTIPLE_MARKS_LABEL, detect_omr

    exam = db.get(m.Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    template_spec = json.loads(exam.template_spec_json) if exam.template_spec_json else None
    questions: list[m.ExamQuestion] = []
    if template_spec:
        questions = (
            db.query(m.ExamQuestion)
            .filter(m.ExamQuestion.exam_id == exam_id)
            .order_by(m.ExamQuestion.order_index)
            .all()
        )
    questions_by_id = {q.id: q for q in questions}

    # Fallback full-page OCR (question_id=None, from a failed alignment) can
    # only be safely graded against a real question when the exam has
    # exactly one non-MCQ/TF question — see _run_bulk_process's grading loop.
    gradable_questions = [
        q for q in questions if (q.question_type or "essay") not in ("mcq", "tf")
    ]
    fallback_question = gradable_questions[0] if len(gradable_questions) == 1 else None

    has_non_omr = (not template_spec) or any(
        (q.question_type or "essay") not in ("mcq", "tf") for q in questions
    )
    if has_non_omr and ocr_pipeline.MODELS is None:
        raise HTTPException(status_code=503, detail="Models not loaded yet")

    sub_ids = [
        sid for (sid,) in (
            db.query(m.Submission.id)
            .filter(m.Submission.exam_id == exam_id, m.Submission.status == "submitted")
            .all()
        )
    ]

    project_root = Path(__file__).resolve().parent.parent
    processed = 0
    failed    = 0
    errors: list[str] = []

    for sub_id in sub_ids:
        sub_db = SessionLocal()
        try:
            sub = sub_db.get(m.Submission, sub_id)
            if not sub:
                failed += 1
                errors.append(f"Submission {sub_id}: not found")
                continue

            files = (
                sub_db.query(m.SubmissionFile)
                .filter(m.SubmissionFile.submission_id == sub.id)
                .order_by(m.SubmissionFile.page_number)
                .all()
            )
            if not files:
                failed += 1
                errors.append(f"Submission {sub.id} ({sub.student_id}): no files uploaded")
                continue

            dest_dir = DATA_ROOT / str(sub.id)
            dest_dir.mkdir(parents=True, exist_ok=True)
            now = datetime.now(timezone.utc)

            # ── OCR ──────────────────────────────────────────────────────────
            for sf in files:
                img_path = project_root / sf.stored_path
                image    = ImageOps.exif_transpose(Image.open(img_path)).convert("RGB")
                aligned  = False

                if template_spec:
                    warped, aligned = detect_and_warp(image, template_spec)
                    if aligned:
                        try:
                            (dest_dir / f"aligned_p{sf.page_number}.png").write_bytes(
                                _pil_to_png_bytes(warped)
                            )
                        except Exception:
                            pass

                        for q in questions:
                            if not q.region_json:
                                continue
                            region = json.loads(q.region_json)
                            qtype  = (q.question_type or "essay")
                            omr_confidence: float | None = None

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
                                crop     = crop_region(warped, region, template_spec)
                                ocr_text, boxes, _ = ocr_pipeline.run_ocr_pipeline(crop)
                                if qtype == "essay":
                                    ocr_text = correct_ocr_text(ocr_text)
                                elif qtype == "identification":
                                    ocr_text = correct_id_text(ocr_text)
                                boxes_data = json.dumps(
                                    [{"x1": b[0], "y1": b[1], "x2": b[2], "y2": b[3]}
                                     for b in boxes]
                                )
                                ans_status = "done"

                            existing = (
                                sub_db.query(m.SubmissionAnswer)
                                .filter(
                                    m.SubmissionAnswer.submission_id == sub.id,
                                    m.SubmissionAnswer.question_id  == q.id,
                                )
                                .first()
                            )
                            if existing:
                                existing.ocr_text       = ocr_text
                                existing.boxes_json     = boxes_data
                                existing.status         = ans_status
                                existing.omr_confidence = omr_confidence
                                existing.updated_at     = now
                            else:
                                sub_db.add(m.SubmissionAnswer(
                                    submission_id=sub.id,
                                    question_id=q.id,
                                    page_number=sf.page_number,
                                    ocr_text=ocr_text,
                                    boxes_json=boxes_data,
                                    status=ans_status,
                                    omr_confidence=omr_confidence,
                                ))
                            sub_db.commit()

                if not aligned:
                    fallback = crop_content_area(image, template_spec)
                    ocr_text, boxes, _ = ocr_pipeline.run_ocr_pipeline(fallback)
                    ocr_text   = correct_ocr_text(ocr_text)
                    boxes_data = json.dumps(
                        [{"x1": b[0], "y1": b[1], "x2": b[2], "y2": b[3]} for b in boxes]
                    )
                    existing = (
                        sub_db.query(m.SubmissionAnswer)
                        .filter(
                            m.SubmissionAnswer.submission_id == sub.id,
                            m.SubmissionAnswer.page_number  == sf.page_number,
                            m.SubmissionAnswer.question_id.is_(None),
                        )
                        .first()
                    )
                    if existing:
                        existing.ocr_text   = ocr_text
                        existing.boxes_json = boxes_data
                        existing.status     = "done"
                        existing.updated_at = now
                    else:
                        sub_db.add(m.SubmissionAnswer(
                            submission_id=sub.id,
                            question_id=None,
                            page_number=sf.page_number,
                            ocr_text=ocr_text,
                            boxes_json=boxes_data,
                            status="done",
                        ))
                    sub_db.commit()

            sub.status = "ocr_done"
            sub_db.commit()

            # ── Grade ─────────────────────────────────────────────────────────
            answers = (
                sub_db.query(m.SubmissionAnswer)
                .filter(m.SubmissionAnswer.submission_id == sub.id)
                .all()
            )
            for ans in answers:
                if not ans.ocr_text:
                    continue
                question = (
                    questions_by_id.get(ans.question_id) if ans.question_id else fallback_question
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
                        _auto_flag(ans, "essay_score_zero", sub_db)
                    elif result.confidence < 0.4:
                        _auto_flag(ans, "essay_low_confidence", sub_db)
                    if ans.question_id is None and question is None:
                        ans.status = "needs_review"
                        _auto_flag(ans, "fallback_ocr_ambiguous_question", sub_db)

                elif qtype in ("mcq", "tf"):
                    max_pts = question.max_points if question else 1.0
                    if ans.ocr_text.strip() == MULTIPLE_MARKS_LABEL:
                        # Two or more bubbles were filled — invalid regardless
                        # of which mark is darkest, so it's an automatic zero.
                        ans.ai_score    = 0.0
                        ans.ai_feedback = (
                            f"Correct answer: {question.correct_answer}. "
                            "Detected: multiple bubbles marked. "
                            "Incorrect — more than one option was filled in, so no "
                            "single answer can be credited. ⚠ Please verify on the original scan."
                        )
                        ans.status = "needs_review"
                        _auto_flag(ans, "omr_multiple_marks", sub_db)
                        continue
                    correct     = (question.correct_answer or "").strip().upper()
                    given       = ans.ocr_text.strip().upper()
                    given_first = given.split()[0] if given else ""
                    match       = (given_first == correct) or (given == correct)
                    ans.ai_score    = max_pts if match else 0.0
                    ans.ai_feedback = (
                        f"Correct answer: {question.correct_answer}. "
                        f"Detected: {ans.ocr_text.strip() or '(none)'}. "
                        + ("Correct." if match else "Incorrect.")
                    )
                    if ans.omr_confidence is not None and ans.omr_confidence < 0.30:
                        ans.ai_feedback += f" ⚠ Low OMR confidence ({ans.omr_confidence:.0%})."
                        ans.status = "needs_review"
                        _auto_flag(ans, "omr_low_confidence", sub_db)
                    elif not ans.ocr_text.strip():
                        ans.status = "needs_review"
                        _auto_flag(ans, "omr_no_detection", sub_db)
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
                        ratio = difflib.SequenceMatcher(None, correct.lower(), given.lower()).ratio()
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
                        _auto_flag(ans, "identification_no_match", sub_db)

                ans.updated_at = now

            sub.status = "graded"
            sub_db.commit()
            processed += 1

        except Exception as exc:
            logger.error("Bulk process: submission %d failed: %s", sub_id, exc)
            failed += 1
            errors.append(f"Submission {sub_id}: {exc}")
        finally:
            sub_db.close()

    return BulkProcessResult(processed=processed, failed=failed, errors=errors)


def _pil_to_png_bytes(img: Image.Image) -> bytes:
    """Helper to encode a PIL image as PNG bytes in memory."""
    import io as _io
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@router.patch(
    "/submissions/{submission_id}/answers/{answer_id}",
    response_model=SubmissionAnswerRead,
)
def teacher_override(
    submission_id: int,
    answer_id: int,
    body: TeacherOverride,
    db: Session = Depends(get_db),
) -> m.SubmissionAnswer:
    """
    Teacher override: set a manual score and optional note on a graded answer.

    The final score shown in the Results page uses teacher_score when set,
    falling back to ai_score otherwise.
    """
    ans = db.get(m.SubmissionAnswer, answer_id)
    if not ans or ans.submission_id != submission_id:
        raise HTTPException(status_code=404, detail="Answer not found")

    question = db.get(m.ExamQuestion, ans.question_id) if ans.question_id else None
    if question and body.teacher_score > question.max_points:
        raise HTTPException(
            status_code=400,
            detail=f"teacher_score {body.teacher_score} exceeds max_points {question.max_points}",
        )

    ans.teacher_score = body.teacher_score
    ans.teacher_note  = body.teacher_note

    # If the teacher provides a reference transcription, compute OCR quality metrics
    if body.reference_text is not None and ans.ocr_text:
        from ai_grader import compute_cer, compute_wer
        ref = body.reference_text.strip()
        hyp = ans.ocr_text.strip()
        ans.cer = round(compute_cer(ref, hyp), 4)
        ans.wer = round(compute_wer(ref, hyp), 4)
        logger.info(
            "CER/WER computed for answer %d: CER=%.4f WER=%.4f",
            ans.id, ans.cer, ans.wer,
        )

    ans.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(ans)
    return ans


# ---------------------------------------------------------------------------
# Phase 21 — Background processing queue
# ---------------------------------------------------------------------------


@router.post("/queue/enqueue/{exam_id}", response_model=QueueEnqueueResult)
def enqueue_exam_submissions(
    exam_id: int,
    db: Session = Depends(get_db),
) -> QueueEnqueueResult:
    """
    Add all 'submitted' submissions for an exam to the background OCR/grade queue.
    Submissions already in the queue or already processed are not re-added.
    """
    from job_queue import QUEUE_STATE as _qs, enqueue_submission

    exam = db.get(m.Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    subs = (
        db.query(m.Submission)
        .filter(m.Submission.exam_id == exam_id, m.Submission.status == "submitted")
        .all()
    )

    # Collect submission IDs already sitting in the queue to avoid duplicates
    pending_ids: set[int] = set()
    temp: list[dict] = []
    while not _qs.queue.empty():
        try:
            j = _qs.queue.get_nowait()
            temp.append(j)
            pending_ids.add(j["submission_id"])
        except Exception:
            break
    for j in temp:          # put them back
        _qs.queue.put_nowait(j)

    enqueued = 0
    already  = 0
    for sub in subs:
        if sub.id in pending_ids:
            already += 1
            continue
        student = db.get(m.Student, sub.student_id)
        label   = f"{student.full_name} (#{sub.id})" if student else f"#{sub.id}"
        enqueue_submission(sub.id, sub.exam_id, label)
        enqueued += 1

    return QueueEnqueueResult(
        enqueued=enqueued,
        already_pending=already,
        queue_size=_qs.pending(),
    )


@router.get("/queue/status", response_model=QueueStatus)
def queue_status() -> QueueStatus:
    """Return the current state of the background processing queue."""
    from job_queue import get_status
    return get_status()


# ---------------------------------------------------------------------------
# Phase 17 — RQ4 Flag log endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/submissions/{submission_id}/flags",
    response_model=list[FlagLogRead],
)
def list_flags(submission_id: int, db: Session = Depends(get_db)) -> list[m.FlagLog]:
    """Return all flag-log entries for answers belonging to a submission."""
    sub = db.get(m.Submission, submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    answer_ids = [a.id for a in sub.answers]
    if not answer_ids:
        return []
    return (
        db.query(m.FlagLog)
        .filter(m.FlagLog.submission_answer_id.in_(answer_ids))
        .all()
    )


@router.post(
    "/submissions/{submission_id}/answers/{answer_id}/flag",
    response_model=FlagLogRead,
    status_code=201,
)
def create_flag(
    submission_id: int,
    answer_id: int,
    body: FlagCreate,
    db: Session = Depends(get_db),
) -> m.FlagLog:
    """Manually flag an answer for review."""
    ans = db.get(m.SubmissionAnswer, answer_id)
    if not ans or ans.submission_id != submission_id:
        raise HTTPException(status_code=404, detail="Answer not found")

    existing = db.query(m.FlagLog).filter(
        m.FlagLog.submission_answer_id == answer_id
    ).first()
    if existing:
        existing.flag_reason  = body.flag_reason
        existing.auto_flagged = False
        db.commit()
        db.refresh(existing)
        return existing

    flag = m.FlagLog(
        submission_answer_id=answer_id,
        flag_reason=body.flag_reason,
        auto_flagged=False,
        auto_flagged_at=datetime.now(timezone.utc),
    )
    db.add(flag)
    db.commit()
    db.refresh(flag)
    return flag


@router.patch(
    "/submissions/{submission_id}/answers/{answer_id}/flag",
    response_model=FlagLogRead,
)
def review_flag(
    submission_id: int,
    answer_id: int,
    body: FlagReview,
    db: Session = Depends(get_db),
) -> m.FlagLog:
    """
    Record a professor's review decision on a flagged (or unflagged) answer.

    review_decision must be one of:
      confirmed_error  — flag was correct (TP)
      false_positive   — flag was wrong, answer was fine (FP)
      verified         — answer was NOT flagged but professor confirms it is correct (TN)
    """
    valid = {"confirmed_error", "false_positive", "verified"}
    if body.review_decision not in valid:
        raise HTTPException(
            status_code=422,
            detail=f"review_decision must be one of: {sorted(valid)}",
        )
    ans = db.get(m.SubmissionAnswer, answer_id)
    if not ans or ans.submission_id != submission_id:
        raise HTTPException(status_code=404, detail="Answer not found")

    flag = db.query(m.FlagLog).filter(
        m.FlagLog.submission_answer_id == answer_id
    ).first()

    now = datetime.now(timezone.utc)
    if flag:
        flag.review_decision = body.review_decision
        flag.reviewed_by     = body.reviewed_by
        flag.reviewed_at     = now
    else:
        # "verified" on an unflagged answer — still log it for TN tracking
        flag = m.FlagLog(
            submission_answer_id=answer_id,
            flag_reason="verified",
            auto_flagged=False,
            auto_flagged_at=now,
            review_decision=body.review_decision,
            reviewed_by=body.reviewed_by,
            reviewed_at=now,
        )
        db.add(flag)

    db.commit()
    db.refresh(flag)
    return flag


@router.delete(
    "/submissions/{submission_id}/answers/{answer_id}/flag",
    status_code=204,
)
def delete_flag(
    submission_id: int,
    answer_id: int,
    db: Session = Depends(get_db),
) -> None:
    """Remove a flag from an answer (e.g. to reset a wrongly auto-flagged entry)."""
    ans = db.get(m.SubmissionAnswer, answer_id)
    if not ans or ans.submission_id != submission_id:
        raise HTTPException(status_code=404, detail="Answer not found")
    flag = db.query(m.FlagLog).filter(
        m.FlagLog.submission_answer_id == answer_id
    ).first()
    if flag:
        db.delete(flag)
        db.commit()


@router.get("/exams/{exam_id}/flagstats", response_model=FlagStats)
def exam_flag_stats(exam_id: int, db: Session = Depends(get_db)) -> FlagStats:
    """
    Compute Precision / Recall for the auto-flagging system on this exam.

    TP  = flags with review_decision = 'confirmed_error'
    FP  = flags with review_decision = 'false_positive'
    TN  = flag rows with review_decision = 'verified'
    FN  = graded answers with NO flag where teacher_score differs from ai_score
          by more than 10% of max_points (proxy for missed errors)

    Precision = TP / (TP + FP)  — of everything flagged, how many were real errors
    Recall    = TP / (TP + FN)  — of all real errors, how many did we catch
    """
    exam = db.get(m.Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    # All graded answers for this exam
    graded_answers = (
        db.query(m.SubmissionAnswer)
        .join(m.Submission, m.SubmissionAnswer.submission_id == m.Submission.id)
        .filter(
            m.Submission.exam_id == exam_id,
            m.SubmissionAnswer.ai_score.isnot(None),
        )
        .all()
    )
    answer_ids = [a.id for a in graded_answers]

    flags = (
        db.query(m.FlagLog)
        .filter(
            m.FlagLog.submission_answer_id.in_(answer_ids),
            m.FlagLog.flag_reason != "verified",  # exclude pure TN rows from count
        )
        .all()
    ) if answer_ids else []

    verified_rows = (
        db.query(m.FlagLog)
        .filter(
            m.FlagLog.submission_answer_id.in_(answer_ids),
            m.FlagLog.review_decision == "verified",
        )
        .all()
    ) if answer_ids else []

    tp = sum(1 for f in flags if f.review_decision == "confirmed_error")
    fp = sum(1 for f in flags if f.review_decision == "false_positive")
    tn = len(verified_rows)

    # FN: unflagged answers where teacher_score meaningfully differs from ai_score
    flagged_ids = {f.submission_answer_id for f in flags}
    fn = 0
    for ans in graded_answers:
        if ans.id in flagged_ids:
            continue
        if ans.teacher_score is None:
            continue
        q = db.get(m.ExamQuestion, ans.question_id) if ans.question_id else None
        max_pts = q.max_points if q else 10.0
        threshold = max(0.5, max_pts * 0.1)
        if abs((ans.teacher_score or 0.0) - (ans.ai_score or 0.0)) >= threshold:
            fn += 1

    precision = (tp / (tp + fp)) if (tp + fp) > 0 else None
    recall    = (tp / (tp + fn)) if (tp + fn) > 0 else None

    return FlagStats(
        exam_id=exam_id,
        exam_code=exam.exam_code,
        total_answers=len(graded_answers),
        total_flagged=len(flags),
        reviewed_count=sum(1 for f in flags if f.review_decision is not None),
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        true_negatives=tn,
        precision=round(precision, 4) if precision is not None else None,
        recall=round(recall, 4)    if recall    is not None else None,
    )


# ---------------------------------------------------------------------------
# Phase 9 — Delete operations (with cascade)
# ---------------------------------------------------------------------------


def _delete_submission_data(sub: m.Submission, db: Session) -> None:
    """
    Delete all children of a submission and the submission itself.
    Physical scan files and aligned images are removed from disk.
    """
    for ans in list(sub.answers):
        if ans.flag:
            db.delete(ans.flag)
        db.delete(ans)
    for sf in list(sub.files):
        try:
            (Path(__file__).resolve().parent.parent / sf.stored_path).unlink(missing_ok=True)
        except Exception:
            pass
        db.delete(sf)
    # Remove submission folder (aligned images, etc.)
    sub_dir = DATA_ROOT / str(sub.id)
    if sub_dir.exists():
        shutil.rmtree(sub_dir, ignore_errors=True)
    # Remove cached student paper PDF
    try:
        (_PAPERS_DIR / f"submission_{sub.id}.pdf").unlink(missing_ok=True)
    except Exception:
        pass
    db.delete(sub)


@router.delete("/submissions/{submission_id}", status_code=204)
def delete_submission(submission_id: int, db: Session = Depends(get_db)) -> None:
    """Delete a submission with all its files, OCR results, and grading data."""
    sub = db.get(m.Submission, submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    _delete_submission_data(sub, db)
    db.commit()


@router.delete("/exams/{exam_id}", status_code=204)
def delete_exam(exam_id: int, db: Session = Depends(get_db)) -> None:
    """
    Delete an exam and everything it owns:
    questions, submissions (+ files + answers), template PDF.
    """
    exam = db.get(m.Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    for sub in list(exam.submissions):
        _delete_submission_data(sub, db)

    for q in list(exam.questions):
        db.delete(q)

    # Remove template PDF from disk
    _template_pdf_path(exam_id).unlink(missing_ok=True)

    db.delete(exam)
    db.commit()


def _delete_student(student: m.Student, db: Session) -> None:
    """Cascade-delete a student: enrollments and all submissions (+ files + answers)."""
    for sub in list(student.submissions):
        _delete_submission_data(sub, db)
    for enr in list(student.enrollments):
        db.delete(enr)
    db.delete(student)


@router.delete("/students/{student_id}", status_code=204)
def delete_student(student_id: str, db: Session = Depends(get_db)) -> None:
    """
    Delete a student by their external school ID.
    Cascades to enrollments and all submissions (+ files + answers).
    """
    student = db.query(m.Student).filter(m.Student.student_id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail=f"Student not found: {student_id}")
    _delete_student(student, db)
    db.commit()


@router.post("/students/bulk-delete", response_model=BulkDeleteResult)
def bulk_delete_students(body: dict, db: Session = Depends(get_db)) -> BulkDeleteResult:
    """
    Delete multiple students by a list of student_id strings.

    Body: {"student_ids": ["2024-0001", "2024-0002", ...]}
    Each deletion cascades to enrollments and all submissions (+ files + answers),
    same as the single-student delete. Unknown IDs are reported as errors and
    skipped rather than aborting the whole batch.
    """
    student_ids: list[str] = body.get("student_ids", [])
    deleted = 0
    errors: list[str] = []
    for sid in student_ids:
        sid = str(sid).strip()
        if not sid:
            continue
        student = db.query(m.Student).filter(m.Student.student_id == sid).first()
        if not student:
            errors.append(f"Student not found: {sid}")
            continue
        _delete_student(student, db)
        deleted += 1
    db.commit()
    return BulkDeleteResult(deleted=deleted, errors=errors)


@router.delete("/classes/{class_id}", status_code=204)
def delete_class(class_id: int, db: Session = Depends(get_db)) -> None:
    """
    Delete a class and everything beneath it:
    enrollments, exams, questions, submissions, files, answers.
    """
    course = db.get(m.CourseClass, class_id)
    if not course:
        raise HTTPException(status_code=404, detail="Class not found")

    for exam in list(course.exams):
        for sub in list(exam.submissions):
            _delete_submission_data(sub, db)
        for q in list(exam.questions):
            db.delete(q)
        _template_pdf_path(exam.id).unlink(missing_ok=True)
        db.delete(exam)

    for enr in list(course.enrollments):
        db.delete(enr)

    db.delete(course)
    db.commit()


# ---------------------------------------------------------------------------
# Phase 9 — Analytics
# ---------------------------------------------------------------------------


def _exam_stats(exam: m.Exam, db: Session) -> ExamStats:
    """Compute analytics for a single exam."""
    questions = (
        db.query(m.ExamQuestion)
        .filter(m.ExamQuestion.exam_id == exam.id)
        .order_by(m.ExamQuestion.order_index)
        .all()
    )
    max_possible = sum(q.max_points for q in questions)
    pass_threshold = max_possible * 0.6

    submissions = db.query(m.Submission).filter(m.Submission.exam_id == exam.id).all()
    graded_subs = [s for s in submissions if s.status == "graded"]

    # Per-submission total scores
    sub_totals: list[float] = []
    for sub in graded_subs:
        answers = db.query(m.SubmissionAnswer).filter(
            m.SubmissionAnswer.submission_id == sub.id
        ).all()
        total = sum(
            (a.teacher_score if a.teacher_score is not None else a.ai_score or 0.0)
            for a in answers
        )
        sub_totals.append(total)

    avg_total = (sum(sub_totals) / len(sub_totals)) if sub_totals else None
    avg_pct   = (avg_total / max_possible * 100) if (avg_total is not None and max_possible > 0) else None
    pass_count = sum(1 for t in sub_totals if t >= pass_threshold)
    fail_count = len(sub_totals) - pass_count

    # Per-question stats
    q_stats: list[QuestionStats] = []
    for q in questions:
        answers = db.query(m.SubmissionAnswer).filter(
            m.SubmissionAnswer.question_id == q.id
        ).all()
        scores = [
            (a.teacher_score if a.teacher_score is not None else a.ai_score)
            for a in answers
            if (a.teacher_score is not None or a.ai_score is not None)
        ]
        q_stats.append(QuestionStats(
            question_id=q.id,
            order_index=q.order_index,
            prompt=q.prompt[:120],
            max_points=q.max_points,
            avg_score=round(sum(scores) / len(scores), 2) if scores else None,
            min_score=round(min(scores), 2) if scores else None,
            max_score=round(max(scores), 2) if scores else None,
            answer_count=len(scores),
        ))

    return ExamStats(
        exam_id=exam.id,
        exam_code=exam.exam_code,
        title=exam.title,
        submission_count=len(submissions),
        graded_count=len(graded_subs),
        max_possible=max_possible,
        avg_total=round(avg_total, 2) if avg_total is not None else None,
        avg_pct=round(avg_pct, 1) if avg_pct is not None else None,
        pass_count=pass_count,
        fail_count=fail_count,
        questions=q_stats,
    )


@router.get("/classes/{class_id}/analytics", response_model=ClassAnalytics)
def class_analytics(class_id: int, db: Session = Depends(get_db)) -> ClassAnalytics:
    """Return aggregate analytics for a class (all exams + per-question stats)."""
    course = db.get(m.CourseClass, class_id)
    if not course:
        raise HTTPException(status_code=404, detail="Class not found")

    student_count = (
        db.query(m.Enrollment).filter(m.Enrollment.class_id == class_id).count()
    )
    exams = db.query(m.Exam).filter(m.Exam.class_id == class_id).order_by(m.Exam.created_at).all()

    return ClassAnalytics(
        class_id=course.id,
        class_code=course.code,
        class_name=course.name,
        student_count=student_count,
        exams=[_exam_stats(ex, db) for ex in exams],
    )


@router.get("/exams/{exam_id}/analytics", response_model=ExamStats)
def exam_analytics(exam_id: int, db: Session = Depends(get_db)) -> ExamStats:
    """Return detailed analytics for a single exam."""
    exam = db.get(m.Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    return _exam_stats(exam, db)


@router.get("/students/{student_id}/analytics", response_model=StudentAnalytics)
def student_analytics(student_id: str, db: Session = Depends(get_db)) -> StudentAnalytics:
    """Return all graded submissions for a student with score summaries."""
    student = db.query(m.Student).filter(m.Student.student_id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail=f"Student not found: {student_id}")

    submissions = (
        db.query(m.Submission)
        .filter(m.Submission.student_id == student.id)
        .order_by(m.Submission.created_at)
        .all()
    )

    sub_stats: list[SubmissionStats] = []
    for sub in submissions:
        exam   = db.get(m.Exam, sub.exam_id)
        course = db.get(m.CourseClass, exam.class_id) if exam else None
        questions = (
            db.query(m.ExamQuestion).filter(m.ExamQuestion.exam_id == sub.exam_id).all()
            if exam else []
        )
        max_possible = sum(q.max_points for q in questions)

        answers = db.query(m.SubmissionAnswer).filter(
            m.SubmissionAnswer.submission_id == sub.id
        ).all()
        scored = [
            (a.teacher_score if a.teacher_score is not None else a.ai_score)
            for a in answers
            if (a.teacher_score is not None or a.ai_score is not None)
        ]
        total_score = round(sum(scored), 2) if scored else None
        pct = round(total_score / max_possible * 100, 1) if (total_score is not None and max_possible > 0) else None

        sub_stats.append(SubmissionStats(
            submission_id=sub.id,
            exam_id=sub.exam_id,
            exam_code=exam.exam_code if exam else "—",
            exam_title=exam.title if exam else "—",
            class_code=course.code if course else "—",
            status=sub.status,
            total_score=total_score,
            max_possible=max_possible,
            pct=pct,
        ))

    return StudentAnalytics(
        student_db_id=student.id,
        student_id=student.student_id,
        full_name=student.full_name,
        submissions=sub_stats,
    )


# ---------------------------------------------------------------------------
# Phase 9 — AI analytics insights (optional, requires GROQ_API_KEY)
# ---------------------------------------------------------------------------


@router.post("/exams/{exam_id}/analyze", response_model=dict)
def analyze_exam(exam_id: int, db: Session = Depends(get_db)) -> dict:
    """Run Groq AI analysis on exam performance data. Returns {analysis: str}."""
    from ai_grader import analyze_exam_performance

    exam = db.get(m.Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    stats = _exam_stats(exam, db)
    try:
        text = analyze_exam_performance(stats.model_dump())
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"AI analysis failed: {e}")
    return {"analysis": text}


@router.post("/students/{student_id}/analyze", response_model=dict)
def analyze_student(student_id: str, db: Session = Depends(get_db)) -> dict:
    """Run Groq AI analysis on a student's submission history. Returns {analysis: str}."""
    from ai_grader import analyze_student_performance

    student = db.query(m.Student).filter(m.Student.student_id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail=f"Student not found: {student_id}")
    stats = student_analytics(student_id, db)
    try:
        text = analyze_student_performance(stats.model_dump())
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"AI analysis failed: {e}")
    return {"analysis": text}


# ---------------------------------------------------------------------------
# Phase 16 — Grade export CSV
# ---------------------------------------------------------------------------


@router.get("/exams/{exam_id}/grades/csv")
def export_grades_csv(exam_id: int, db: Session = Depends(get_db)) -> Response:
    """
    Download a per-student grade sheet for an exam as CSV.

    Columns: student_id, student_name, question_order, question_prompt,
             question_type, max_points, ai_score, teacher_score, final_score,
             groq_confidence, omr_confidence, cer, wer, status
    """
    exam = db.get(m.Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    questions = (
        db.query(m.ExamQuestion)
        .filter(m.ExamQuestion.exam_id == exam_id)
        .order_by(m.ExamQuestion.order_index)
        .all()
    )
    submissions = (
        db.query(m.Submission)
        .filter(m.Submission.exam_id == exam_id)
        .all()
    )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "student_id", "student_name",
        "question_order", "question_prompt", "question_type",
        "max_points", "ai_score", "teacher_score", "final_score",
        "groq_confidence", "omr_confidence", "cer", "wer", "status",
    ])

    for sub in submissions:
        student = db.get(m.Student, sub.student_id)
        sid  = student.student_id if student else str(sub.student_id)
        name = student.full_name  if student else "Unknown"

        answers_by_q: dict[int, m.SubmissionAnswer] = {}
        for ans in sub.answers:
            if ans.question_id:
                answers_by_q[ans.question_id] = ans

        for q in questions:
            ans = answers_by_q.get(q.id)
            final = None
            if ans:
                final = ans.teacher_score if ans.teacher_score is not None else ans.ai_score
            writer.writerow([
                sid, name,
                q.order_index, q.prompt[:80], q.question_type,
                q.max_points,
                ans.ai_score      if ans else "",
                ans.teacher_score if ans else "",
                final             if final is not None else "",
                ans.groq_confidence if ans else "",
                ans.omr_confidence  if ans else "",
                ans.cer             if ans else "",
                ans.wer             if ans else "",
                ans.status          if ans else "not_submitted",
            ])

    csv_bytes = buf.getvalue().encode("utf-8-sig")  # BOM for Excel compatibility
    filename  = f"grades_{exam.exam_code}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Phase 9 — CSV bulk student import
# ---------------------------------------------------------------------------


def _read_tabular_dict_rows(
    raw: bytes, required_columns: list[str] | None = None,
) -> tuple[list[dict], list[str]]:
    """
    Read an uploaded CSV file into a list of dict rows keyed by lowercased,
    stripped header text. XLSX uploads are converted to CSV client-side
    before reaching this endpoint (see frontend/src/lib/excelImport.js) —
    this only ever needs to handle CSV.

    If `required_columns` is given, the header is validated to contain all
    of them (case-insensitive) before any rows are returned — this catches a
    missing column even when the file has zero data rows, not just when a
    later row-access happens to come up empty.

    Returns (rows, errors) — errors is only non-empty (with rows empty) for
    structural problems: a missing header row or missing required column(s).
    """
    try:
        text = raw.decode("utf-8-sig")   # handles BOM from Excel CSV exports
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return [], ["File has no header row."]
    header_norm = {h.strip().lower(): h for h in reader.fieldnames if h}
    if required_columns:
        missing = [c for c in required_columns if c not in header_norm]
        if missing:
            return [], [f"Missing required column(s): {', '.join(missing)}"]
    rows = [{k: row.get(v) for k, v in header_norm.items()} for row in reader]
    return rows, []


@router.post("/students/import", response_model=ImportResult)
async def import_students(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> ImportResult:
    """
    Bulk import students from a CSV file (the UI also accepts XLSX and
    converts it to CSV client-side before uploading here).

    Expected columns (header row required): student_id, full_name, email (optional)
    Duplicate student_id rows are skipped. Returns created / skipped / error counts.
    """
    raw = await file.read()
    rows, read_errors = _read_tabular_dict_rows(raw)
    if read_errors:
        return ImportResult(created=0, skipped=0, errors=read_errors)

    created = 0
    skipped = 0
    errors: list[str] = []

    for i, row in enumerate(rows, start=2):   # start=2: row 1 is header
        sid  = (row.get("student_id") or "").strip()
        name = (row.get("full_name")  or "").strip()
        email = (row.get("email") or "").strip() or None

        if not sid or not name:
            errors.append(f"Row {i}: missing student_id or full_name")
            continue

        if db.query(m.Student).filter(m.Student.student_id == sid).first():
            skipped += 1
            continue

        db.add(m.Student(student_id=sid, full_name=name, email=email))
        created += 1

    db.commit()
    return ImportResult(created=created, skipped=skipped, errors=errors)


# ---------------------------------------------------------------------------
# Phase 10 — Rubric / question CSV import
# ---------------------------------------------------------------------------


@router.post("/exams/{exam_id}/questions/import", response_model=QuestionImportResult)
async def import_questions(
    exam_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> QuestionImportResult:
    """
    Bulk-import questions from a CSV file into an exam, across all four question types.

    Expected columns (header required):
      prompt          — optional; auto-generated as "Question N" if omitted
      question_type   — optional, defaults to "essay"; one of essay, mcq, tf, identification
      rubric_text     — required for essay questions, ignored otherwise
      max_points      — optional, defaults to 10
      choices         — mcq only; pipe-separated choice text, e.g. "Oxygen|Carbon Dioxide|Nitrogen|Hydrogen"
                         (position maps to bubble letter: 1st = A, 2nd = B, ...)
      correct_answer  — required for mcq (a letter matching a choices position, e.g. "B"),
                         tf ("True" or "False"), and identification (the expected answer text)

    Rows are assigned order_index starting after the current highest question index.
    Skips rows with an invalid question_type, missing rubric_text (essay), or missing
    correct_answer (mcq/tf/identification) — same requirements as adding a question manually.
    """
    exam = db.get(m.Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    # Start order after existing questions
    existing_max = db.query(m.ExamQuestion).filter(
        m.ExamQuestion.exam_id == exam_id
    ).count()
    next_order = existing_max + 1

    reader = csv.DictReader(io.StringIO(text))
    created = 0
    errors: list[str] = []
    valid_types = ("essay", "mcq", "tf", "identification")

    for i, row in enumerate(reader, start=2):
        prompt  = (row.get("prompt") or "").strip()
        qtype   = (row.get("question_type") or "essay").strip().lower()
        rubric  = (row.get("rubric_text") or "").strip()
        correct = (row.get("correct_answer") or "").strip()
        choices_raw = (row.get("choices") or "").strip()
        try:
            max_pts = float((row.get("max_points") or "10").strip())
        except ValueError:
            max_pts = 10.0

        if qtype not in valid_types:
            errors.append(
                f"Row {i}: invalid question_type '{qtype}' — must be one of "
                f"{', '.join(valid_types)} — skipped"
            )
            continue

        if qtype == "essay" and not rubric:
            errors.append(f"Row {i}: missing rubric_text for essay question — skipped")
            continue

        if qtype in ("mcq", "tf", "identification") and not correct:
            errors.append(f"Row {i}: missing correct_answer for {qtype} question — skipped")
            continue

        choices_json = None
        if qtype == "mcq" and choices_raw:
            choice_list = [c.strip() for c in choices_raw.split("|") if c.strip()]
            if choice_list:
                choices_json = json.dumps(choice_list)

        if not prompt:
            prompt = f"Question {next_order}"

        db.add(m.ExamQuestion(
            exam_id=exam_id,
            order_index=next_order,
            prompt=prompt,
            rubric_text=rubric if qtype == "essay" else None,
            max_points=max_pts,
            question_type=qtype,
            choices_json=choices_json,
            correct_answer=correct or None,
        ))
        next_order += 1
        created += 1

    db.commit()
    return QuestionImportResult(created=created, errors=errors)


# ---------------------------------------------------------------------------
# Phase 15 — Rubric management + exam duplication
# ---------------------------------------------------------------------------


@router.post("/exams/{exam_id}/rubrics/import", response_model=RubricImportResult)
async def import_rubrics(
    exam_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> RubricImportResult:
    """
    Update rubric_text on existing questions from a CSV file.

    Expected columns (header required): order_index, rubric_text
    Rows are matched to existing questions by order_index.
    Skips rows where order_index doesn't match an existing question.
    Does NOT create new questions.
    """
    exam = db.get(m.Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    # Build a map of order_index → question
    questions = (
        db.query(m.ExamQuestion)
        .filter(m.ExamQuestion.exam_id == exam_id)
        .all()
    )
    q_by_order: dict[int, m.ExamQuestion] = {q.order_index: q for q in questions}

    reader = csv.DictReader(io.StringIO(text))
    updated = 0
    errors: list[str] = []

    for i, row in enumerate(reader, start=2):
        raw_order = (row.get("order_index") or "").strip()
        rubric = (row.get("rubric_text") or "").strip()

        if not raw_order:
            errors.append(f"Row {i}: missing order_index — skipped")
            continue
        try:
            order_idx = int(raw_order)
        except ValueError:
            errors.append(f"Row {i}: order_index '{raw_order}' is not an integer — skipped")
            continue

        q = q_by_order.get(order_idx)
        if not q:
            errors.append(f"Row {i}: no question with order_index {order_idx} — skipped")
            continue

        q.rubric_text = rubric or None
        updated += 1

    db.commit()
    return RubricImportResult(updated=updated, errors=errors)


@router.delete("/exams/{exam_id}/rubrics", status_code=204)
def clear_rubrics(exam_id: int, db: Session = Depends(get_db)) -> None:
    """Remove rubric_text from every question in the exam."""
    exam = db.get(m.Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    db.query(m.ExamQuestion).filter(m.ExamQuestion.exam_id == exam_id).update(
        {"rubric_text": None}, synchronize_session=False
    )
    db.commit()


_RUBRIC_CRITERIA_COLUMNS = [
    "criterion_name", "level_label", "level_points", "level_description",
]


@router.post("/exams/{exam_id}/rubric-criteria/parse", response_model=RubricCriteriaParseResult)
async def parse_rubric_criteria(
    exam_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> RubricCriteriaParseResult:
    """
    Parse an uploaded CSV rubric template into structured criteria (the UI
    also accepts XLSX and converts it to CSV client-side before uploading here).

    In-memory only — does NOT write to the database. The frontend rubric
    builder prefills its editable table from the response; the teacher must
    still save the question for anything to persist.

    Expected columns (header required, case-insensitive): criterion_name,
    level_label, level_points, level_description. One row per (criterion,
    level) pair — consecutive rows sharing the same criterion_name are
    grouped into a single criterion with multiple levels. A criterion's max
    points is NOT a column — it is always derived as the highest level_points
    among its rows (kept in sync with the levels that define it).
    """
    exam = db.get(m.Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    raw = await file.read()
    rows, read_errors = _read_tabular_dict_rows(raw, required_columns=_RUBRIC_CRITERIA_COLUMNS)
    if read_errors:
        return RubricCriteriaParseResult(criteria=[], errors=read_errors)
    rows = [row for row in rows if any((row.get(c) or "").strip() for c in _RUBRIC_CRITERIA_COLUMNS)]

    # Group rows into criteria, preserving first-seen order (case-insensitive
    # match on criterion_name so minor casing differences don't split a
    # criterion across two groups).
    criteria_order: list[str] = []
    criteria_map: dict[str, dict] = {}
    errors: list[str] = []

    for i, row in enumerate(rows, start=2):
        name = str(row.get("criterion_name") or "").strip()
        if not name:
            errors.append(f"Row {i}: missing criterion_name — skipped")
            continue

        label = str(row.get("level_label") or "").strip()
        lvl_points_raw = str(row.get("level_points") or "").strip()
        lvl_points = None
        if lvl_points_raw:
            try:
                lvl_points = float(lvl_points_raw)
            except ValueError:
                errors.append(
                    f"Row {i}: level_points '{lvl_points_raw}' is not a number — level skipped"
                )
        description = str(row.get("level_description") or "").strip()

        key = name.lower()
        if key not in criteria_map:
            criteria_map[key] = {"name": name, "max_points": 0.0, "levels": []}
            criteria_order.append(key)

        if label and lvl_points is not None:
            criteria_map[key]["levels"].append({
                "label": label, "points": lvl_points, "description": description,
            })
            # max_points is derived, not a column — always the highest level_points seen so far.
            criteria_map[key]["max_points"] = max(criteria_map[key]["max_points"], lvl_points)

    criteria = [criteria_map[key] for key in criteria_order]
    return RubricCriteriaParseResult(criteria=criteria, errors=errors)


@router.post("/exams/{exam_id}/duplicate", response_model=ExamRead)
def duplicate_exam(exam_id: int, db: Session = Depends(get_db)) -> m.Exam:
    """
    Clone an exam (structure only — no submissions, no template).

    Creates a new exam in the same class with "_copy" appended to the code and
    title, then copies all questions (rubrics, choices, correct answers included).
    The new exam has no template_spec_json so the teacher must re-generate the PDF.
    """
    src = db.get(m.Exam, exam_id)
    if not src:
        raise HTTPException(status_code=404, detail="Exam not found")

    # Generate a unique exam_code
    base_code = src.exam_code + "_copy"
    candidate = base_code
    suffix = 2
    while db.query(m.Exam).filter(m.Exam.exam_code == candidate).first():
        candidate = f"{base_code}{suffix}"
        suffix += 1

    new_exam = m.Exam(
        class_id=src.class_id,
        exam_code=candidate,
        title=src.title + " (copy)",
        description=src.description,
        template_spec_json=None,
    )
    db.add(new_exam)
    db.flush()  # populate new_exam.id

    src_questions = (
        db.query(m.ExamQuestion)
        .filter(m.ExamQuestion.exam_id == exam_id)
        .order_by(m.ExamQuestion.order_index)
        .all()
    )
    for q in src_questions:
        db.add(m.ExamQuestion(
            exam_id=new_exam.id,
            order_index=q.order_index,
            prompt=q.prompt,
            question_type=q.question_type,
            rubric_text=q.rubric_text,
            rubric_criteria_json=q.rubric_criteria_json,
            max_points=q.max_points,
            choices_json=q.choices_json,
            correct_answer=q.correct_answer,
            region_json=None,  # template not copied
        ))

    db.commit()
    db.refresh(new_exam)
    logger.info("Duplicated exam %d → %d (%s)", exam_id, new_exam.id, candidate)
    return new_exam


# ---------------------------------------------------------------------------
# Phase 10 — Batch scan upload with QR auto-identification
# ---------------------------------------------------------------------------


def _read_qr_from_bytes(raw: bytes) -> dict | None:
    """
    Decode a QR code from raw image bytes using OpenCV's built-in detector.
    Returns the parsed JSON payload dict or None if no QR found / invalid JSON.
    """
    import numpy as np
    np_arr = np.frombuffer(raw, np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if img is None:
        return None

    detector = cv2.QRCodeDetector()
    data, _, _ = detector.detectAndDecode(img)
    if not data:
        return None
    try:
        return json.loads(data)
    except Exception:
        return None


@router.post("/exams/{exam_id}/submissions/batch", response_model=BatchUploadResult)
async def batch_upload_submissions(
    exam_id: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> BatchUploadResult:
    """
    Batch-upload multiple scanned exam papers for an exam.

    For each uploaded image:
      1. Read QR code (encodes {"exam_id": N, "student_id": "..."}).
      2. Validate exam_id matches this endpoint's exam_id.
      3. Look up the student; they must already be enrolled.
      4. Create (or reuse) a Submission for that student + exam.
      5. Save the image and create a SubmissionFile record.

    Returns a per-file result list. Files with unreadable QR codes or
    students not found are reported as errors but do not abort the batch.
    """
    exam = db.get(m.Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    _ensure_data_root()
    results: list[BatchFileResult] = []
    now = datetime.now(timezone.utc)

    for upload in files:
        fname = os.path.basename(upload.filename or "scan.jpg")
        raw   = await upload.read()

        # 1. Read QR
        qr_data = _read_qr_from_bytes(raw)
        if qr_data is None:
            results.append(BatchFileResult(
                filename=fname, status="no_qr",
                student_id=None, student_name=None,
                submission_id=None,
                detail="No QR code detected in image",
            ))
            continue

        # 2. Validate exam
        if qr_data.get("exam_id") != exam_id:
            results.append(BatchFileResult(
                filename=fname, status="wrong_exam",
                student_id=None, student_name=None,
                submission_id=None,
                detail=f"QR exam_id={qr_data.get('exam_id')} does not match this exam ({exam_id})",
            ))
            continue

        # 3. Find student
        qr_student_id = str(qr_data.get("student_id", "")).strip()
        student = db.query(m.Student).filter(m.Student.student_id == qr_student_id).first()
        if not student:
            results.append(BatchFileResult(
                filename=fname, status="error",
                student_id=qr_student_id, student_name=None,
                submission_id=None,
                detail=f"Student '{qr_student_id}' not found in registry",
            ))
            continue

        # 4. Find or create submission
        sub = (
            db.query(m.Submission)
            .filter(
                m.Submission.exam_id == exam_id,
                m.Submission.student_id == student.id,
            )
            .first()
        )
        if not sub:
            # Check enrollment
            enr = (
                db.query(m.Enrollment)
                .filter(
                    m.Enrollment.class_id == exam.class_id,
                    m.Enrollment.student_id == student.id,
                )
                .first()
            )
            if not enr:
                results.append(BatchFileResult(
                    filename=fname, status="error",
                    student_id=qr_student_id, student_name=student.full_name,
                    submission_id=None,
                    detail=f"Student '{qr_student_id}' is not enrolled in this class",
                ))
                continue
            sub = m.Submission(exam_id=exam_id, student_id=student.id, status="draft")
            db.add(sub)
            db.commit()
            db.refresh(sub)

        # 5. Save file
        dest_dir = DATA_ROOT / str(sub.id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        page_number = (
            db.query(m.SubmissionFile)
            .filter(m.SubmissionFile.submission_id == sub.id)
            .count()
        ) + 1
        dest_path = dest_dir / f"p{page_number}_{fname}"
        dest_path.write_bytes(raw)

        rel = str(dest_path.relative_to(Path(__file__).resolve().parent.parent))
        sf = m.SubmissionFile(
            submission_id=sub.id,
            page_number=page_number,
            original_filename=fname,
            stored_path=rel.replace("\\", "/"),
        )
        db.add(sf)
        sub.status = "submitted"
        sub.updated_at = now
        db.commit()

        results.append(BatchFileResult(
            filename=fname, status="ok",
            student_id=student.student_id,
            student_name=student.full_name,
            submission_id=sub.id,
            detail=None,
        ))

    ok_count    = sum(1 for r in results if r.status == "ok")
    error_count = len(results) - ok_count
    return BatchUploadResult(results=results, ok_count=ok_count, error_count=error_count)
