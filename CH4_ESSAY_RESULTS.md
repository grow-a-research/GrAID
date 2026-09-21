# Essay Feature — Chapter 4 Results, Chapter 3 Edits, Evidence Index

Prepared 2026-09-21. Essay scoring uses `openai/gpt-oss-120b` via Groq.
All figures are reproducible; see Part C.

---

# PART A — Chapter 4: Essay Grading Results

## 4.x.1 Transcription Accuracy

Essays are graded from transcribed text, so transcription was measured separately
from scoring. Reference transcriptions were prepared using the double-transcription
procedure in Chapter 3.

| Measure | Mean | Median |
|---|---|---|
| Character Error Rate | 0.0254 | 0.0050 |
| Word Error Rate | 0.0482 | 0.0236 |
| Character accuracy (1 − CER) | 97.5% | 99.5% |

*n = 54 essay responses.*

Transcription accuracy averaged 97.5%, exceeding the 80% threshold set for this
study. Only two responses exceeded 10% CER. Transcription is therefore not the
limiting factor on essay grading quality.

## 4.x.2 Scoring Agreement With Professors

Scoring was evaluated on 200 essays, each scored independently by all five
professors on Content, Organization, and Language (0–15). The reference score is
the mean of the five professors' totals. These essays are digital text, so this
measures scoring judgment without transcription error.

| Measure | Value |
|---|---|
| Pearson r | 0.578 (p < .001) |
| Essay Score Agreement (within 10%) | 64.5% |
| Mean absolute difference | 8.83% |
| Mean signed difference (system − professor) | +4.00% |
| Quadratic weighted kappa | 0.519 |

The system's scores correlate significantly with professor consensus, with 64.5% of
essays within the 10% threshold defined in Chapter 3. The system scores slightly
more generously than the professors overall (+4.00%).

For comparison, the professors agreed with each other at a mean pairwise kappa of
0.460, ranging from 0.361 to 0.548. The system's agreement with professor consensus
(0.519) falls inside that range.

## 4.x.3 Comparison With Human Inter-Rater Agreement

To compare the system and the professors on equal terms, each professor's scores
were correlated against the mean of the other four, and the system's scores were
correlated against that same four-professor mean.

| Rater held out | Professor vs. other four | System vs. same four |
|---|---|---|
| Professor 1 | .620 | .562 |
| Professor 2 | .637 | .574 |
| Professor 3 | .535 | .571 |
| Professor 4 | .661 | .554 |
| Professor 5 | .538 | .562 |
| **Mean** | **.598** | **.565** |

A professor agrees with a four-professor consensus at r = .598 on average. The
system agrees with the same consensus at r = .565 — a difference of .034. For two
of the five professors, the system agreed with the remaining panel more closely
than that professor did.

This is the main finding on essay scoring: the system disagrees with expert
judgment by roughly the same margin that the experts disagree with each other. The
professors' own agreement ranged from .361 to .548, showing the degree of legitimate
variation in expert essay scoring.

These results match published work. Johnson and Zhang (2024) reported QWK .437 for
GPT-4o on 13,121 essays; Yoo et al. (2025), using the same DREsS corpus, reported
.307 for GPT-3.5 and .471 for a fine-tuned BERT model. The present results fall
within this range. Scale and rubric differences prevent direct ranking; these are
reported as context.

## 4.x.4 Professor Perception

Professors described conditional trust with retained oversight. Five of six
respondents said without prompting that they still reviewed essay scores
themselves, while describing the scores as broadly reasonable. Trust depended on
rubric clarity and legibility: one professor trusted the scores "to some extent, but
I would still review them, especially for essays," and was "more confident when the
students' answers were clear and the scoring criteria were straightforward."

This coexisted with strong positive assessments: all six reported reduced grading
effort and all six would adopt the system. Professors treated it as a support tool
whose output they would verify — the same usage pattern the quantitative results
support.

## 4.x.5 Summary

| Claim | Result |
|---|---|
| Transcribes handwritten essays accurately | Supported — 97.5% character accuracy |
| Scores agree with expert judgment | Supported — r = .578, 64.5% within 10%, κ = .519 |
| Agrees comparably to a human rater | Supported — system r = .565 vs. professor r = .598 |
| Professors find it useful and would adopt it | Supported — all six respondents |

---

# PART B — Required Edits to Existing Chapters

Page numbers refer to `GrAid_Thesis_Revised_Ch1-3.pdf`.

## B1. Remove the classification model — CRITICAL

It appears on pages 5, 11, 12, 15, 18, 20, 21, 26, 27, 48, 49, 51, 55, 56, 58, and
again on 73–88, 123, 137. Highest priority:

| Page | What is there | Action |
|---|---|---|
| 5 | Abstract lists "the performance of an ordinal essay rubric-band classification model" | Delete that clause |
| 11–12 | Notations define n, yᵢ, ŷᵢ, 1[·], x₁x₂x₃, β₁β₂β₃, θ, z, P(Y ≤ j) | Delete classifier symbols; keep CER/WER, QWK, flag, rubric symbols |
| 55 | Entire "Classification performance" subsection | Delete |
| 56 | Timetable row "Data analysis and classifier training" | Change to "Data analysis" |
| 15, 18, 20, 21, 26, 27 | Scope, objectives, Chapter 1 references | Rewrite using the framing below |

Replacement wherever the scoring method needs describing:

> Essay responses are scored by a large language model conditioned on the
> instructor's rubric, producing per-criterion scores and justifications. The
> method is evaluated by comparing the system's scores against independent
> professor scores on the same essays.

## B2. Fix the SUS / NASA-TLX contradiction — CRITICAL

Page 53 says both instruments "are not used." Both were administered (n = 6).
Replace with:

> In addition to the semi-structured interview, the System Usability Scale and an
> adapted six-item Raw NASA Task Load Index were administered as supplementary
> descriptive measures. With six respondents, both are reported descriptively,
> without inferential statistics or reliability coefficients, and serve to
> triangulate the interview findings rather than constitute a separate usability
> study.

## B3. Revise the QWK ≥ .70 target — CRITICAL

Page 54 sets a target of .70. The observed value is .519. Replace with:

> Following Williamson et al. (2012), agreement is computed as quadratic weighted
> kappa. The .70 benchmark that framework proposes was established for operational
> commercial scoring engines validated against large, professionally normed rater
> panels, and is not an appropriate absolute threshold for a five-rater,
> single-institution study. Agreement is instead evaluated relative to the
> professors' own inter-rater agreement on the same essays.

**Do not state a numeric ≤ .10 margin.** Resampling shows that criterion is met in
only 55.1% of cases when the system is compared against individual professors —
essentially a coin flip, and not something to claim as passed. Against professor
consensus it holds in 99.8% of resamples. Evaluate agreement relative to human
agreement without binding it to a fixed numeric gap.

## B4. Remove flag precision/recall from the essay evaluation — CRITICAL

Chapter 3 (page 54) defines Precision = TP/(TP+FP) and Recall = TP/(TP+FN) for
review flags, and the Data Gathering Procedure (page 53, step 6) commits to having
professors record review decisions. The essay results no longer report these
measures, so Chapter 3 must not promise them for essays.

Either scope the flagging metrics to objective item types only — "flagging precision
and recall are reported for multiple-choice, true-or-false, and identification
items" — or remove the measures from Chapter 3 entirely. Leaving them defined in the
Statistical Treatment section while Chapter 4 reports nothing against them is an
internal contradiction a reader will find.

Note also that no essay flag was ever confirmed as an error (14 of 14 reviewed were
resolved "not an error"), so precision for essays would compute to 0%, and recall
cannot be computed at all without an independent professor score for every unflagged
essay.

## B5. Correct the shared-essay description — IMPORTANT

Pages 53 and 54 refer to "the 15 shared essays" / "15 shared DREsS essays." All 200
essays were scored by all five professors. Replace with "all 200 essays, each
scored independently by all five professors."

## B6. Resolve the Justification Quality rating form — IMPORTANT

Page 52 lists a 5-point Likert form rating how well each justification reflects the
rubric. No data exists for it. Collect it or remove the instrument from Chapter 3
and the evaluation table.

## B7. Update the timetable — MINOR

Table 2 (page 56) marks data gathering and analysis "Not started." Update statuses
and replace PENDING ranges with actual dates.

## B8. Clear remaining PENDING markers — MINOR

Pages 49 and 57 contain bracketed `[PENDING — ...]` notes needing dates and
documentation of requirement-gathering consultations.

---

# PART C — Evidence and File Locations

## C1. Scoring agreement (200 essays)

| Item | Location |
|---|---|
| Script | `classification_model/run_essay_agreement.py` |
| Command | `python -m classification_model.run_essay_agreement` |
| Results | `classification_model/essay_agreement_results.md` |
| Per-essay table (gitignored) | `classification_model/dress_data/essay_agreement_per_essay.csv` |
| Dataset | `classification_model/dress_data/final_200_combined.csv` |
| Raw professor scores | `classification_model/dress_data/_raw_professor_scores_combined.csv` |
| Source pickles | `_raw_professor_scores.pkl` (original 200), `_replacement_28_raw.pkl` |
| Workbook loader | `classification_model/professor_ground_truth.py` |
| Rubric | `classification_model/dress_pipeline.py` (`RUBRIC_CRITERIA`, max 15) |

Checks passed: consensus rebuilt from raw per-professor scores matches the stored
consensus to 0.000000 points; all 200 essays have five professors' scores; the 28
essays excluded from the original cohort match the documented replacement list.
The QWK implementation was validated against `sklearn.metrics.cohen_kappa_score`
(quadratic weights) to floating-point precision.

## C2. Transcription accuracy

| Item | Location |
|---|---|
| Database | `data/app.db`, `submission_answers.cer` / `.wer` |
| Filter | join `exam_questions` on `question_type = 'essay'`, `cer IS NOT NULL` |
| Pipeline | `ocr_pipeline.py`, `essay_ocr.py`, `vast_ocr_server.py` |
| Models | Surya text-line detection + Qwen2.5-VL-7B-Instruct |

**Re-verify before submission.** This database changed during preparation (essays
with reference transcriptions went 46 → 54). Freeze a snapshot and recompute.

## C3. Review flags (not reported in Part A)

Retained for reference; the essay results no longer report flagging measures.

| Item | Location |
|---|---|
| Database | `data/app.db`, `flag_log.review_decision` |
| Flag creation | `routers/api_v1.py`, `_auto_flag()` |
| Review endpoint | `routers/api_v1.py`, `PATCH /submissions/{id}/answers/{id}/flag` |
| Statistics | `routers/api_v1.py`, `GET /exams/{id}/flagstats` |
| Interface | `frontend/src/pages/ResultsPage.jsx`, `FlagBadge` |

Current essay state: 15 flags raised, 14 reviewed, all resolved "not an error."

## C4. Professor perception

| Item | Detail |
|---|---|
| File | `GrAid System Feedback Form (Responses).xlsx` (Downloads) |
| Contents | 10 SUS items, 6 adapted NASA-TLX items, 3 open-ended, n = 6 |
| Computed | SUS M = 76.2, Mdn = 77.5, range 65.0–85.0; Raw TLX M = 1.89 / 5 |
| Interview | Appendix B, TAM-based, 9 questions |

Disclose: two respondents share a surname and may be the same person (confirm
n = 5 or 6); three rated the system both "unnecessarily complex" and "easy to use"
at scale extremes, consistent with reverse-item inattention; the TLX used an adapted
5-point scale without pairwise weighting, so it is Raw TLX and not comparable to
published norms.

## C5. Essay scoring implementation

| Item | Location |
|---|---|
| Grader | `ai_grader.py` — `grade_essay()`, `grade_answer_structured()` |
| Model | `openai/gpt-oss-120b` via Groq (`_GROQ_MODEL`, line 29) |

## C6. Comparison studies

| Study | Result | Status |
|---|---|---|
| Yoo et al. (2025), ACL — same DREsS corpus | GPT-3.5 QWK .307; fine-tuned BERT .471 | Verified |
| Johnson & Zhang (2024), Sci Reports 14:30064 | GPT-4o QWK .437 | Verified |
| Mizumoto & Eguchi (2023), RMAL 2(2):100050 | GPT-3 QWK .388 | **Unverified** — publisher 403; confirm before citing |
| Emirtekin & Karasu (2026), IJONMES | Human–LLM agreement not different from human–human | Abstract only |
