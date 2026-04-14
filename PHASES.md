# Handwritten Test Paper Checker — Project Phases

## System Flow
**Create Class → Enroll Students → Create Exam → Add Questions → Generate PDF → Print & Distribute → Collect & Upload Scans → Check Papers → View Results**

---

## Phase 1 — Project Scaffolding ✅
- FastAPI backend skeleton
- Vite + React + Tailwind frontend
- Python virtual environment (`.venv`)
- Folder structure: `routers/`, `data/`, `alembic/`, `frontend/`

---

## Phase 2 — OCR Pipeline ✅
- Surya OCR for line/region detection
- Qwen2.5-VL-7B-Instruct (4-bit quantization) for handwriting transcription
- `SKIP_MODEL_LOAD=1` env var for fast data-platform-only startup
- Legacy `/extract` endpoint — kept as a raw debug/test tool
- Frontend: OCR Tool (under Tools menu)

---

## Phase 3 — Database Platform ✅
- SQLAlchemy 2.0 ORM models: `CourseClass`, `Student`, `Enrollment`, `Exam`,
  `ExamQuestion`, `Submission`, `SubmissionFile`, `SubmissionAnswer`
- Alembic migrations: `0001_initial`, `0002_phase3_additions`
- Smart `init_db()` — detects pre-Alembic DBs, stamps, upgrades
- Full CRUD REST API under `/api/v1/`
- Frontend tabs: Classes, Students, Exams, Submissions

---

## Phase 4 — Printable PDF Generation ✅
- A4 PDF via fpdf2 with exam/student metadata header
- 3× ArUco markers (DICT_4X4_50, IDs 0/1/2) at TL/BL/BR corners
- 1× QR code at TR encoding `exam_id` (+ `student_id` on personalised copies)
- Ruled answer boxes per question sized to fill available space
- Template spec JSON stored in `Exam.template_spec_json` (positions in mm)
- Region JSON stored in `ExamQuestion.region_json` (answer box bounds)
- Files stored: `data/templates/`, `data/submissions/`, `data/papers/`

---

## Phase 5 — Scan Alignment + Per-Question OCR ✅
- `ocr_alignment.py`: ArUco detection, RANSAC homography, perspective warp
- Crops each answer region using `region_json` (mm → pixels)
- Runs Surya + Qwen on each crop individually → `SubmissionAnswer` per `question_id`
- Fallback to full-page OCR if fewer than 2 markers detected
- Student PDFs cached to `data/papers/submission_{id}.pdf`
- `SubmissionRead` includes `files` list

---

## Phase 6 — AI Grading ✅
- `ai_grader.py`: Groq API (Llama-3.3-70B-Versatile, free tier)
- Rubric-based scoring per question with constructive written feedback
- `compute_cer()` and `compute_wer()` utilities (populated when reference available)
- DB columns on `SubmissionAnswer`: `ai_score`, `ai_feedback`, `cer`, `wer`,
  `teacher_score`, `teacher_note`
- `POST /submissions/{id}/grade` — runs AI grading
- `PATCH /submissions/{id}/answers/{answer_id}` — teacher override
- Alembic migration `0003_ai_grading_columns`

---

## Phase 7 — Frontend: Results Page + UX Restructure ✅
- **Results tab**: per-question OCR text, AI score bars, AI feedback, teacher override forms
- **Submissions tab**: streamlined — upload scan + single Process button (OCR → Grade)
- **Navigation**: Classes | Students | Exams | Submissions | Results | Tools (OCR Tool)
- `api.js`: added `grade()` and `override()` calls
- Cloudflare Quick Tunnel setup for mobile/public access
- Built frontend served from FastAPI (`frontend/dist`)

---

## Phase 8 — PDF & OCR Quality Fixes ✅
Fixes for known issues discovered during testing.

**PDF Layout fixes:**
- ✅ Question prompt cutoff — answer box positioned dynamically via `get_y()`
  after `multi_cell`, not a fixed budget
- ✅ Header text overlapping markers/QR — class/exam code rows now start at
  `title_x = 28mm` (right of TL ArUco) and end before `QR_X = 175mm`
- ✅ Template download button shows immediately if `template_spec_json` exists

**OCR fixes:**
- ✅ Fallback path (no ArUco) — crops to content area below header line using
  `crop_content_area()` to exclude question prompts and header text
- ✅ Image preprocessing pipeline (`preprocess_scan`): denoise (NL-means) →
  deskew (Hough lines, skip if angle <0.5° or >15°) → CLAHE contrast enhancement
- ✅ Crop-level preprocessing (`preprocess_crop`): CLAHE + unsharp mask sharpen
  applied to every answer region before Surya/Qwen
- ✅ Camera capture in Submissions tab — `getUserMedia` webcam/phone camera with
  live viewfinder, capture button, preview before upload
- ✅ Post-OCR correction + essay restructuring via Groq — after Qwen transcription,
  send raw text to Groq to: (1) fix garbled characters / misread letters, and
  (2) restructure output into proper essay form (sentence capitalisation,
  punctuation, paragraph breaks) without adding or rephrasing content
- ✅ Store and serve the perspective-corrected (warped) image:
  save to `data/submissions/{id}/aligned_p{n}.png` during OCR,
  expose via `GET /submissions/{id}/aligned-image/{page}`,
  display in Results page alongside extracted text

**AI Grading improvement:**
- More specific feedback prompt — instruct Groq to quote specific parts of the
  student's answer, identify which sentences address the rubric and which are
  off-topic, and provide targeted improvement suggestions

---

## Phase 9 — Data Management & Analytics ✅
**Delete operations (with cascade):**
- `DELETE /classes/{id}` — cascades to enrollments, exams, questions, submissions, files, answers
- `DELETE /students/{id}` — cascades to enrollments and submissions
- `DELETE /exams/{id}` — cascades to questions, submissions, files, answers; deletes PDF files from disk
- `DELETE /submissions/{id}` — cascades to files, answers; deletes scan images from disk
- `window.confirm` dialog on frontend before any delete; physical files removed from disk

**Analytics tab (new frontend tab):**
- Class overview: per-exam average score, pass/fail count (≥60%), per-question breakdown
- Exam breakdown: per-question avg/min/max score, answer count
- Student tracker: all submissions per student with scores and percentage
- All computed from `SubmissionAnswer` data; respects teacher overrides
- ✅ Optional AI Analysis button on Exam breakdown and Student tracker —
  sends analytics data to Groq (Llama-3.3-70B) for actionable bullet-point insights;
  endpoints: `POST /exams/{id}/analyze`, `POST /students/{id}/analyze`

**Bulk student import via CSV:**
- `POST /students/import` — accepts CSV (columns: `student_id`, `full_name`, `email`)
- Frontend file picker in Students tab; reports created / skipped / errors
- Skips duplicate student IDs; handles Excel BOM encoding

**Also fixed:** enrolled student list display bug in ClassesPage (was failing to resolve names)

---

## Phase 10 — Advanced Workflow ✅
**Question / rubric CSV import:**
- `POST /exams/{id}/questions/import` — CSV columns: `prompt`, `rubric_text`, `max_points`
- Auto-assigns `order_index` after existing questions; skips rows missing prompt or rubric
- Frontend: "Import CSV" button in Exams tab question section with hint row for format
- Reports created count + row-level errors

**Batch submission upload with QR auto-identification:**
- `POST /exams/{id}/submissions/batch` — accepts multiple image files (multipart)
- Per image: reads QR code using `cv2.QRCodeDetector` (no extra library needed)
- QR payload: `{"exam_id": N, "student_id": "..."}` — validates exam match + enrollment
- Auto-creates submission if none exists; saves file and sets status → `submitted`
- Returns per-file result: ok / no_qr / wrong_exam / error with student name
- Frontend: "Batch upload scans" panel in Submissions tab (visible when exam is selected);
  shows colour-coded results per file after upload

---

## Phase 11 — UX & Workflow Improvements ✅
**App rename:** ✅
- Rename brand to **GrAId** (App.jsx header, index.html `<title>`, FastAPI app title)

**Student management:** ✅
- Edit student info inline (full_name, email) — `PATCH /students/{id}` + inline form in Students tab
- CSV template download button in Students tab — generates CSV with headers + example row (frontend-only)

**Bulk enroll improvements:** ✅
- Bulk enroll in Classes tab: multi-select picker from registered non-enrolled students
- CSV upload of student IDs directly in Classes tab
- Downloadable CSV template pre-filled with non-enrolled students for that class
- `POST /classes/{id}/enrollments/bulk` backend endpoint

**Rubric CSV fix:** ✅
- Make `prompt` column optional in `POST /exams/{id}/questions/import`
- Auto-generate question prompt as "Question N" if omitted

**Batch PDF generation:** ✅
- `GET /exams/{id}/papers/zip` — generates personalised PDFs for all enrolled students, returns ZIP
- Frontend "Download all papers (ZIP)" button in Exams tab

---

## Phase 12 — New Question Types ✅
- DB migration: add `question_type` column (`essay` | `mcq` | `tf` | `identification`) to `ExamQuestion`
- Add `choices_json` column for MCQ options (list of strings A-D)
- Add `correct_answer` column for MCQ / T-F / Identification correct answer storage
- MCQ / T-F question creation UI in Exams tab (radio for type, choices input for MCQ)
- Auto-scoring for Identification via regex + fuzzy matching (no Groq needed)
- Auto-scoring for MCQ / T-F via exact match (no Groq needed)
- Groq grading skipped for MCQ / T-F / Identification (use deterministic scoring)
- PDF layout: MCQ renders lettered bubbles; T-F renders True/False bubbles; essay renders ruled box

---

## Phase 13 — OMR Engine ✅
- Bubble centre positions (cx_mm, cy_mm, r_mm) stored per-choice in `region_json["bubbles"]`
  when generating MCQ/TF templates (pdf_generator.py)
- `omr_engine.py`: Otsu binarisation → circular mask per bubble → fill ratio
  → returns `(detected_label, confidence, fill_ratios_dict)`
- OCR endpoint dispatches to OMR for MCQ/TF questions when bubble positions are available;
  falls back to regular OCR if bubbles list is empty (legacy templates)
- Smart model-load check: `SKIP_MODEL_LOAD=1` respected for pure MCQ/TF exams
- `omr_confidence` float column added to `SubmissionAnswer` (migration `0005`)
- Status set to `needs_review` when confidence < 0.30 or no bubble detected
- Grading feedback includes ⚠ low-confidence warning when OMR confidence < 30%
- Results page: colour-coded OMR confidence bar (green ≥60%, amber ≥30%, red < 30%),
  "review needed" badge for low-confidence answers

---

## Phase 14 — Question Editing & Input Validation ✅
- `ExamQuestionUpdate` schema (all fields optional)
- `PATCH /exams/{id}/questions/{qid}` — partial update with structural change detection:
  structural changes (type, choices, max_points) clear `region_json` + `template_spec_json`
- `DELETE /exams/{id}/questions/{qid}` — removes question, always clears template
- `correct_answer` enforced at creation and edit for MCQ / T-F / Identification (422 on missing)
- Inline edit UI per question card in Exams tab: ✎ opens edit form in place, ✕ deletes
- `pdf_generator.py`: prompt truncation raised 200 → 500 chars; `essay_h` formula fixed
  to divide remaining space only among essay questions (not total question count)

---

## Phase 15 — Rubric Management & Exam Duplication ✅
- `POST /exams/{id}/rubrics/import` — CSV (`order_index`, `rubric_text`) updates rubrics
  on existing questions by order index; does NOT create new questions
- `DELETE /exams/{id}/rubrics` — clears rubric_text from all questions in an exam
- `POST /exams/{id}/duplicate` — clones exam + all questions (rubrics, choices, correct
  answers) to a new draft exam; `_copy` suffix appended to code and title; no template copied
- `RubricImportResult` schema: `updated`, `errors`
- Frontend Exams tab: "Update rubrics CSV" button + "Clear rubrics" button (shown when
  rubrics exist) + "Duplicate exam" button in exam header
- CSV hint row updated to show both question and rubric CSV formats

---

## Phase 16 — Grading Engine Improvements ✅
- Skip `correct_ocr_text` for MCQ/TF without bubbles (single-letter answers must not be rephrased)
- CER/WER computed when teacher provides a `reference_text` in the override form (ground-truth
  transcription); stored in `SubmissionAnswer.cer` / `.wer`
- `groq_confidence` (0–1) returned by Groq in essay grading JSON; stored in new DB column
  (migration `0006`); displayed as colour-coded bar in Results (green ≥70%, amber ≥40%, red <40%)
- Reference transcription textarea shown in teacher override form (essay only); CER/WER shown
  below override note after saving
- Configurable fuzzy match thresholds for Identification via query params `fuzzy_full` (default
  0.85) and `fuzzy_partial` (default 0.60) on `POST /submissions/{id}/grade`
- Groq retry with exponential backoff (`_MAX_RETRIES=3`, base delay 2 s, doubles each attempt)
  applied to all Groq calls (grade, correct_ocr_text, analyze_exam, analyze_student)
- `GET /exams/{id}/grades/csv` — BOM-encoded CSV grade sheet (per-student × per-question)
  with ai_score, teacher_score, final_score, groq_confidence, omr_confidence, CER, WER
- "Download grade sheet (CSV)" button in Results tab left panel

---

## Phase 17 — RQ4 Flag Log ✅
- New `FlagLog` DB table (migration `0007`): one row per flagged answer tracking
  `flag_reason`, `auto_flagged`, `review_decision`, `reviewed_by`, `reviewed_at`
- Auto-flag triggers during grading:
  - Essay: `ai_score == 0` → `essay_score_zero`; Groq confidence < 0.4 → `essay_low_confidence`
  - MCQ/TF: OMR confidence < 0.30 → `omr_low_confidence`; no bubble → `omr_no_detection`
  - Identification: score == 0 → `identification_no_match`
- Flag endpoints:
  - `GET /submissions/{id}/flags` — list flags for a submission
  - `POST /submissions/{id}/answers/{answer_id}/flag` — manually flag an answer
  - `PATCH /submissions/{id}/answers/{answer_id}/flag` — record review decision
    (`confirmed_error` / `false_positive` / `verified`)
  - `DELETE /submissions/{id}/answers/{answer_id}/flag` — remove flag
- `GET /exams/{id}/flagstats` — computes TP/FP/FN/TN, Precision, Recall
  (FN estimated from teacher overrides on unflagged answers)
- Results tab: `FlagBadge` per answer card — shows reason, action buttons
  ("Confirm error" / "Not an error" / "⚑ Flag" / "✓ Mark as verified")
- RQ4 Flag Statistics panel below the answer list — shows all metrics, auto-refreshes
  after each grading run and after each review decision

---

## Phase 18 — Processed Paper View in Results ✅
- New `GET /submissions/{id}/original-image/{page}` endpoint — serves the raw uploaded
  scan (before perspective correction) directly from the stored SubmissionFile path
- Replaced `AlignedScanPanel` with `ProcessedPaperPanel` — a 3-tab viewer in Results:
  - **Aligned scan** — perspective-corrected image (`aligned_p{n}.png`)
  - **Original scan** — raw uploaded image (new endpoint)
  - **Student PDF** — embedded iframe of the personalised exam paper; falls back to a
    "generate template first" message when no paper exists; includes download button
- Page selector shown automatically when the submission spans multiple pages
- Panel visible as soon as the submission is past "draft" (even before OCR is run,
  so original scan is always viewable)

---

## Phase 19 — OCR / OMR Quality ✅
- Per-bubble adaptive Otsu: local patch extracted around each bubble (3× radius
  padding), Otsu applied on that patch → robust to uneven lighting / shadowing
- Morphological open + close (elliptic kernel, ~r/4 px) applied after binarization
  to remove speckle noise and fill small gaps inside filled marks
- Blur / quality pre-check via Laplacian variance before OCR; threshold = 80
- Low-quality pages collected as `quality_warnings` list in new `OcrResult`
  response schema (`{ answers, quality_warnings }`)
- Amber warning banner in Submissions tab when OCR detects a blurry scan;
  includes sharpness score and retake suggestion; OCR still proceeds

---

## Phase 20 — UX & Workflow Polish ✅
- **Bulk process**: `POST /exams/{id}/submissions/process-all` — runs OCR + AI grading
  for every `submitted` submission sequentially; reports processed/failed counts + per-submission errors;
  frontend shows "Process all pending (N)" card when pending submissions exist
- **OMR bubble grid clickable**: in Results `AnswerCard` for MCQ/TF, a row of circular bubble
  buttons lets the teacher click any option → auto-saves a teacher override with computed score
  (full if matches correct_answer, 0 otherwise) + note "Manual bubble override: X"
- **Camera alignment guide**: A4-ratio frame overlay (210:297) with corner brackets and
  "Align paper within frame" label rendered over the camera viewfinder
- **Template outdated banner**: amber banner in Exams tab when questions exist but
  `template_spec_json` is null (i.e. template was never generated or was cleared by an edit)
