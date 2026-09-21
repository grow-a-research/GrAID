# DREsS_New Descriptive Analysis — Pre-Classifier Results

**Dataset:** 500-essay stratified sample from DREsS_New (Yoo et al., ACL 2025),
seed=42, proportional to the full 1,911-essay eligible population's band
distribution (Fair 182 / Good 148 / Poor 119 / Excellent 51).

**AI grader:** `openai/gpt-oss-120b` via Groq, structured per-criterion
grading (Content/Organization/Language, 1-5 pts each, max 15 total),
`clean_text=True` (no OCR/transcription step — DREsS essays are plain
digital text).

**Ground truth:** DREsS_New's own expert-assigned scores
(`content + organization + language`), not re-graded by any professor.

This file contains only aggregate statistics computed from the 500 essays —
no essay text or per-essay identifiable content, consistent with keeping
DREsS's restricted-access essay content out of this public repository.

---

## 1. Scoring bias

**Formula — signed bias (mean difference):**

```
bias = (1/n) * Σ(AI_score_pct_i − GT_score_pct_i)
```

Positive = AI over-scores on average; negative = AI under-scores.

**Formula — mean absolute error (MAE):**

```
MAE = (1/n) * Σ|AI_score_pct_i − GT_score_pct_i|
```

| Metric | Value |
|---|---|
| n | 500 |
| Mean AI score_pct | 62.46% |
| Mean GT score_pct | 69.59% |
| Bias (AI − GT) | **−7.13 points** |
| MAE | 15.58 points |
| % of essays where AI < GT | 64.6% |

**Interpretation:** the AI grader scores lower than DREsS's human experts on
nearly two-thirds of essays, by an average of ~7 points on a 0-100 scale.
This is a systematic, one-directional pattern, not symmetric noise.

---

## 2. Correlation (ranking agreement)

**Formula — Pearson correlation coefficient:**

```
r = Σ[(AI_i − AI_mean)(GT_i − GT_mean)] / √[Σ(AI_i − AI_mean)² · Σ(GT_i − GT_mean)²]
```

| Metric | Value |
|---|---|
| Pearson r (AI score_pct vs. GT score_pct) | **0.167** |

**Interpretation:** weak. This was measured earlier on a partial,
band-incomplete sample (r=0.153) and hypothesized to improve once all four
bands were represented — it did not meaningfully change (0.153 → 0.167) now
that the full, correctly-stratified 500 (including Excellent and enough
Poor essays) is in. This suggests the weak correlation is a real property
of this AI-grader/rubric combination, not primarily a restricted-range
artifact of the earlier partial sample.

---

## 3. Essay Score Agreement (the thesis metric)

**Formula:** convert both scores to the rubric's native 15-point scale, then
compute the % of essays where the two scores are within 1 point:

```
AI_15  = AI_score_pct  / 100 × 15
GT_15  = GT_score_pct  / 100 × 15
agreement% = (1/n) * Σ[ 1 if |AI_15_i − GT_15_i| ≤ 1 else 0 ] × 100
```

| Metric | Value |
|---|---|
| Essay Score Agreement (within 1 pt / 15) | **25.4%** |

**Interpretation:** low, and directly explained by the −7.13-point bias
above — a systematic offset this size will fail a strict ±1-point bar on
most essays regardless of ranking quality. Worth discussing with your
adviser as a limitation or a case for a grading-prompt calibration pass in
future work.

---

## 4. Naive band-classification baseline (no trained model)

**Formula:** apply the same cutoffs used to build ground-truth bands
directly to the AI's raw score, with no fitted model at all:

```
naive_band(pct) = Excellent  if pct ≥ 90
                   Good       if 75 ≤ pct < 90
                   Fair       if 60 ≤ pct < 75
                   Poor       if pct < 60

naive_accuracy = (1/n) * Σ[ 1 if naive_band(AI_i) == GT_band_i else 0 ] × 100
```

| Metric | Value |
|---|---|
| Naive exact-match accuracy | **33.6%** |

**Confusion matrix (rows = true band, columns = naive AI band):**

| True \ Naive | Fair | Good | Poor | Excellent |
|---|---|---|---|---|
| Excellent | 30 | 7 | 14 | **0** |
| Fair | 87 | 17 | 78 | 0 |
| Good | 74 | 21 | 53 | 0 |
| Poor | 46 | 13 | 60 | 0 |

**Notable finding:** the AI's raw score **never once** crossed the 90%
naive-Excellent threshold across all 500 essays — not even for the 51
essays DREsS's experts rated Excellent. This is the clearest single
illustration of the scoring bias, and a strong, concrete justification for
why a trained classifier (which learns its own thresholds from the data,
rather than assuming the AI's raw scale lines up with the human one) is
necessary rather than just reading the AI's score directly.

---

## 5. Confidence

**Descriptive statistics** (`clean_text=True` prompt, i.e. the fixed version):

| Statistic | Value |
|---|---|
| Mean | 0.799 |
| Std. dev. | 0.043 |
| Min | 0.65 |
| Max | 0.91 |
| Correlation with \|AI − GT\| error | **0.131** |

**Interpretation:** confidence still clusters narrowly (0.65–0.91) and still
shows only a weak relationship to actual error, even after the
`clean_text=True` prompt fix. The fix appears to have modestly widened the
range and modestly strengthened the error-correlation (see the old-prompt
comparison in step 5 of the training plan for a direct before/after), but
confidence remains the weakest of the three classifier inputs. Recommend
stating this explicitly in the thesis rather than presenting all three
inputs as equally diagnostic.

---

## 6. Spread

| Statistic | Value |
|---|---|
| Mean | 25.70 |
| Std. dev. | 11.33 |
| Min | 0.0 |
| Max | 80.0 |

No red flags — spread varies meaningfully across essays, consistent with it
being a usable classifier input.

---

## Next step

Section 4's naive baseline (33.6% exact accuracy, 0% Excellent recall) is
the number the trained ordinal classifier needs to beat to justify its
existence. That fitting step (train_ordinal_classifier + 5-fold
cross-validation) is the next phase, not yet run.
