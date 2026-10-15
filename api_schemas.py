from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, PlainSerializer


def _utc_iso(d: datetime) -> str:
    """Naive datetimes in this app are UTC; send them with a Z so browsers
    convert to the viewer's local time instead of treating them as local."""
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


UtcDateTime = Annotated[datetime, PlainSerializer(_utc_iso, return_type=str, when_used="json")]


# --- Course class ---
class CourseClassCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)


class CourseClassRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    created_at: datetime


# --- Student ---
class StudentCreate(BaseModel):
    student_id: str = Field(..., min_length=1, max_length=64)
    full_name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr | None = None


class StudentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: str
    full_name: str
    email: str | None


class StudentUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=1, max_length=255)
    email: EmailStr | None = None


# --- Enrollment ---
class EnrollmentCreate(BaseModel):
    """Enroll by external student_id string (school ID)."""

    student_id: str = Field(..., min_length=1, max_length=64)


class EnrollmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    class_id: int
    student_id: int
    enrolled_at: datetime


class RosterEntry(BaseModel):
    student_id: str
    full_name: str
    email: str | None
    access_code: str | None
    redeemed: bool
    redeemed_at: datetime | None


# --- Exam ---
class ExamCreate(BaseModel):
    class_id: int
    exam_code: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    due_at: datetime | None = None      # optional deadline (ISO 8601, any timezone)


class ExamReleaseUpdate(BaseModel):
    released: bool


class ExamAutoGradeUpdate(BaseModel):
    enabled: bool


class ExamDeadlineUpdate(BaseModel):
    due_at: datetime | None = None      # null clears the deadline


class ExamRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    class_id: int
    exam_code: str
    title: str
    description: str | None
    template_spec_json: str | None
    due_at: UtcDateTime | None = None
    results_released_at: UtcDateTime | None = None
    auto_grade: bool = False
    auto_grade_started_at: UtcDateTime | None = None
    auto_grade_finished_at: UtcDateTime | None = None
    created_at: datetime


# --- Question ---
# question_type: "essay" | "mcq" | "tf" | "identification"


# --- Structured rubric (criteria x performance levels) ---
class RubricLevel(BaseModel):
    label: str = Field(..., min_length=1, max_length=128)
    points: float = Field(..., ge=0)
    description: str = Field(default="", max_length=2000)


class RubricCriterion(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    max_points: float = Field(..., ge=0)
    levels: list[RubricLevel] = Field(default_factory=list)


class ExamQuestionCreate(BaseModel):
    order_index: int = Field(default=1, ge=1)
    prompt: str = Field(..., min_length=1)
    question_type: str = Field(default="essay", max_length=32)
    rubric_text: str | None = Field(None)          # required for essay, optional otherwise
    # Structured rubric — JSON-encoded list[RubricCriterion]. When present,
    # takes over from rubric_text for grading/PDF export; max_points is
    # recomputed server-side as the sum of criteria max_points.
    rubric_criteria_json: str | None = None
    max_points: float = Field(default=10.0, ge=0)
    choices_json: str | None = None                 # MCQ only — JSON list of strings
    correct_answer: str | None = None               # MCQ letter, "True"/"False", or "|"-separated accepted answers
    case_sensitive: bool = False                    # identification only


class ExamQuestionUpdate(BaseModel):
    prompt: str | None = Field(None, min_length=1)
    question_type: str | None = Field(None, max_length=32)
    rubric_text: str | None = None
    rubric_criteria_json: str | None = None
    max_points: float | None = Field(None, ge=0)
    choices_json: str | None = None
    correct_answer: str | None = None
    case_sensitive: bool | None = None
    order_index: int | None = Field(None, ge=1)


class ExamQuestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    exam_id: int
    order_index: int
    prompt: str
    question_type: str
    rubric_text: str | None
    rubric_criteria_json: str | None
    max_points: float
    choices_json: str | None
    correct_answer: str | None
    case_sensitive: bool
    region_json: str | None


# --- Submission ---
class SubmissionCreate(BaseModel):
    exam_id: int
    # Accept the external school-issued student_id string, not the internal DB pk.
    student_id: str = Field(..., min_length=1, max_length=64, description="External school student ID")


class SubmissionFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    submission_id: int
    page_number: int
    original_filename: str
    stored_path: str


class SubmissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    exam_id: int
    student_id: int
    status: str
    uploaded_by: str | None = None
    created_at: datetime
    updated_at: datetime
    files: list[SubmissionFileRead] = []


# --- Submission summary (list view with student info inlined) ---
class SubmissionSummary(BaseModel):
    id: int
    status: str
    student_id: str        # external school ID
    student_name: str
    uploaded_by: str | None = None   # "student" | "teacher" | None
    submitted_at: UtcDateTime | None = None
    is_late: bool = False            # student submitted after the exam's deadline
    created_at: datetime
    updated_at: datetime


# --- Submission answer (OCR + grading results) ---
class SubmissionAnswerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    submission_id: int
    question_id: int | None
    page_number: int
    ocr_text: str | None
    boxes_json: str | None
    status: str
    # Phase 6 — AI grading
    ai_score: float | None
    ai_feedback: str | None
    cer: float | None
    wer: float | None
    # Teacher override
    teacher_score: float | None
    teacher_note: str | None
    # Phase 13 — OMR confidence (MCQ/TF only, None for essay/identification)
    omr_confidence: float | None
    # Phase 16 — Groq grading confidence (essay only, None for other types)
    groq_confidence: float | None
    # Suggested band from the ordinal classification model (essay with a
    # structured rubric only; experimental — see band_classifier.py)
    ai_band: str | None = None
    ai_band_probs_json: str | None = None
    ai_spread: float | None = None
    # Phase 21 — Laplacian variance of the answer crop (OCR scan clarity proxy)
    ocr_clarity: float | None
    # Qwen's lowest line confidence for this transcription (0–1). None on
    # MCQ/TF, and on answers OCR'd before the field existed — None is
    # "unknown", not "low". Pairs with groq_confidence to form the combined
    # confidence the review flag uses (see answer_confidence.py).
    ocr_confidence: float | None = None
    reviewed_at: datetime | None = None
    # Computed: teacher_score takes priority over ai_score
    @property
    def final_score(self) -> float | None:
        return self.teacher_score if self.teacher_score is not None else self.ai_score

    created_at: datetime
    updated_at: datetime


# --- Teacher override ---
class TeacherOverride(BaseModel):
    # Optional so a reference_text-only request can compute CER/WER without
    # also having to submit a score override (see teacher_override()).
    teacher_score: float | None = Field(default=None, ge=0)
    teacher_note: str | None = None
    # Optional ground-truth transcription — when provided, CER/WER are computed
    # against ocr_text to measure OCR accuracy for that answer.
    reference_text: str | None = None


# --- Analytics ---
class QuestionStats(BaseModel):
    question_id: int
    order_index: int
    prompt: str
    max_points: float
    avg_score: float | None
    min_score: float | None
    max_score: float | None
    # Number of graded submissions the item was evaluated over. Blank and
    # unscored answers are included (scored 0), so this equals
    # ExamStats.graded_count and the per-item numbers reconcile with the totals.
    answer_count: int

    # --- Item analysis ---
    question_type: str = "essay"
    correct_answer: str | None = None
    # How "correct" was decided for this item, shown next to the counts.
    correct_basis: str = ""
    correct_count: int = 0
    # Incorrect includes blank answers; blank_count is the blank subset of it.
    incorrect_count: int = 0
    blank_count: int = 0
    # Answers still in needs_review — informational, counts may shift after review.
    needs_review_count: int = 0
    pct_correct: float | None = None          # difficulty index, 0–100
    # Upper-vs-lower 27% group difference in score fraction (-1..1);
    # None when too few graded submissions for it to mean anything.
    discrimination_index: float | None = None
    discrimination_note: str | None = None
    # MCQ/TF only: how many students chose each option (incl. "(blank)").
    choice_counts: dict[str, int] | None = None


class ItemResponseRow(BaseModel):
    """One student's response to one question — the source row behind item analysis."""
    answer_id: int | None
    submission_id: int
    student_id: str
    response: str | None
    score: float | None
    score_source: str          # "teacher" | "AI" | "none"
    outcome: str               # "correct" | "incorrect" | "blank"
    status: str | None         # SubmissionAnswer.status; None when no answer row exists


class ExamStats(BaseModel):
    exam_id: int
    exam_code: str
    title: str
    submission_count: int
    graded_count: int
    max_possible: float
    avg_total: float | None
    avg_pct: float | None
    pass_count: int       # score >= 60 % of max_possible
    fail_count: int
    questions: list[QuestionStats]


class ClassAnalytics(BaseModel):
    class_id: int
    class_code: str
    class_name: str
    student_count: int
    exams: list[ExamStats]


class SubmissionStats(BaseModel):
    submission_id: int
    exam_id: int
    exam_code: str
    exam_title: str
    class_code: str
    status: str
    total_score: float | None
    max_possible: float
    pct: float | None


class StudentAnalytics(BaseModel):
    student_db_id: int
    student_id: str
    full_name: str
    submissions: list[SubmissionStats]


# --- CSV import ---
class ImportResult(BaseModel):
    created: int
    skipped: int
    errors: list[str]


# --- Bulk enroll ---
class BulkEnrollResult(BaseModel):
    enrolled: int
    skipped: int
    errors: list[str]


# --- Bulk delete students ---
class BulkDeleteResult(BaseModel):
    deleted: int
    errors: list[str]


# --- Bulk create submissions (one draft per enrolled student) ---
class BulkSubmissionResult(BaseModel):
    created: int             # new draft submissions made
    skipped: int             # students that already had a submission
    total_enrolled: int      # roster size for the exam's class
    submissions: list[SubmissionSummary]


# --- Phase 10: Question CSV import ---
class QuestionImportResult(BaseModel):
    created: int
    errors: list[str]


# --- Phase 15: Rubric CSV import ---
class RubricImportResult(BaseModel):
    updated: int
    errors: list[str]


# --- Structured rubric CSV/XLSX parse (in-memory, no DB write) ---
class RubricCriteriaParseResult(BaseModel):
    criteria: list[RubricCriterion]
    errors: list[str]


# --- Phase 17: Flag log ---
class FlagLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    submission_answer_id: int
    flag_reason: str
    auto_flagged: bool
    auto_flagged_at: datetime
    reviewed_by: str | None
    review_decision: str | None   # confirmed_error | false_positive | verified | None
    reviewed_at: datetime | None
    created_at: datetime


class FlagReview(BaseModel):
    """Body for PATCH /submissions/{id}/answers/{answer_id}/flag."""
    review_decision: str   # confirmed_error | false_positive | verified
    reviewed_by: str | None = None


class FlagCreate(BaseModel):
    """Body for manually flagging an answer."""
    flag_reason: str = "manual"


class FlagLogWithContext(BaseModel):
    """A flag row enriched with student/question context, for the exam-wide flagged-answers list."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    submission_answer_id: int
    submission_id: int
    student_name: str
    student_id: str          # external school ID
    question_order_index: int | None
    question_prompt: str | None
    question_type: str | None
    ai_score: float | None
    teacher_score: float | None
    flag_reason: str
    auto_flagged: bool
    auto_flagged_at: datetime
    reviewed_by: str | None
    review_decision: str | None
    reviewed_at: datetime | None
    created_at: datetime


class ReviewQueueItem(BaseModel):
    """One answer waiting for the teacher: needs_review status and/or an unreviewed flag."""
    answer_id: int
    submission_id: int
    student_id: str            # external school ID
    student_name: str
    question_id: int | None
    question_order_index: int | None
    question_prompt: str | None
    question_type: str | None
    max_points: float | None
    ai_score: float | None
    reason: str                # the flag reason, or "needs_review" when only the status applies
    flagged: bool              # has an unreviewed flag
    status: str


class FlagStats(BaseModel):
    """Per-exam precision/recall stats for the auto-flagging system."""
    exam_id: int
    exam_code: str
    total_answers: int        # answers that have been graded
    total_flagged: int        # flags raised (auto + manual, excl. verified)
    reviewed_count: int       # flags that have a review_decision
    true_positives: int       # review_decision = confirmed_error
    false_positives: int      # review_decision = false_positive
    false_negatives: int      # unflagged answers where teacher_score differs from ai_score
    true_negatives: int       # review_decision = verified
    precision: float | None   # TP / (TP + FP); None if no reviewed flags
    recall: float | None      # TP / (TP + FN); None if no data


# --- Phase 19: OCR result wrapper (includes quality warnings) ---
class OcrResult(BaseModel):
    answers: list[SubmissionAnswerRead]
    quality_warnings: list[str] = []


# --- Phase 20: Bulk process result ---
class BulkProcessResult(BaseModel):
    processed: int
    failed: int
    errors: list[str] = []


class BulkProcessStatus(BaseModel):
    processing: bool


# --- Phase 21: Queue status ---
class QueueCurrentJob(BaseModel):
    submission_id: int
    label: str


class QueueStatus(BaseModel):
    pending: int
    current: QueueCurrentJob | None
    completed: int
    failed: int
    total_enqueued: int
    recent_errors: list[str] = []
    is_running: bool


class QueueEnqueueResult(BaseModel):
    enqueued: int
    already_pending: int = 0
    queue_size: int


class ReprocessRequest(BaseModel):
    """Submissions the teacher picked for a re-run of OCR + grading."""
    submission_ids: list[int]


# --- Phase 10: Batch scan upload ---
class BatchFileResult(BaseModel):
    filename: str
    status: str          # 'ok' | 'error' | 'no_qr' | 'wrong_exam'
    student_id: str | None
    student_name: str | None
    submission_id: int | None
    detail: str | None


class BatchUploadResult(BaseModel):
    results: list[BatchFileResult]
    ok_count: int
    error_count: int
