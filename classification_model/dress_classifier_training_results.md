# DREsS_New Classifier Training Results — Step 3

**Dataset:** the same 500-essay stratified sample used in Step 2
(`dress_training_combined.csv`), Fair 182 / Good 148 / Poor 119 / Excellent 51.

**Model:** ordinal logistic regression (`statsmodels.OrderedModel`,
`distr="logit"`), 3 predictors (`score_pct`, `confidence`, `spread`),
predicting one of 4 ordered bands (Poor < Fair < Good < Excellent).

This file contains only aggregate statistics and the trained formula — no
essay text or per-essay identifiable content, consistent with keeping
DREsS's restricted-access content out of this public repository.

---

## 1. The model and how it's fit

**Ordinal logistic regression formula:**

```
z = β1·score_pct + β2·confidence + β3·spread
```

`z` is a continuous latent score. It's converted into a band prediction by
comparing it against 3 fitted threshold cutoffs (`τ1 < τ2 < τ3`):

```
predicted_band = Poor        if z < τ1
                  Fair        if τ1 ≤ z < τ2
                  Good        if τ2 ≤ z < τ3
                  Excellent   if z ≥ τ3
```

**How β and τ are estimated:** maximum likelihood estimation (MLE) — the
`BFGS` optimizer searches for the (β1, β2, β3, τ1, τ2, τ3) values that
maximize the log-likelihood of observing the actual training labels, given
the ordinal-logit probability model:

```
P(band ≤ k | x) = 1 / (1 + exp(-(τ_k - z)))     [cumulative logit link]
```

This is fit once on the full 500 rows to get the final formula, reported
below.

---

## 2. The trained formula (fit on all 500 essays)

```
z = (0.0237 × score_pct) + (2.0730 × confidence) + (-0.0009 × spread)
```

**Coefficient significance** (Wald test, from `statsmodels`' `OrderedModel`
summary — p < 0.05 conventionally means "statistically distinguishable from
zero"):

| Feature | Coefficient (β) | Std. Error | p-value | Significant? |
|---|---|---|---|---|
| `score_pct` | 0.0237 | 0.007 | **0.0004** | **Yes** |
| `confidence` | 2.0730 | 1.977 | 0.2943 | **No** |
| `spread` | -0.0009 | 0.008 | 0.9097 | **No** |

**Fitted thresholds (on the z-scale):**

| Boundary | z-value |
|---|---|
| Poor / Fair | 1.9218 |
| Fair / Good | 3.5337 |
| Good / Excellent | 5.3242 |

**Interpretation:** only `score_pct` carries statistically real predictive
signal. `confidence`'s coefficient looks large (2.07) but its standard
error is also large (1.98) — the 95% confidence interval for its true
effect spans from -1.80 to +5.95, which includes zero, meaning the data
cannot rule out "confidence has no effect at all." `spread`'s coefficient
is essentially zero either way (p=0.91). **This confirms, with a formal
significance test rather than just a raw correlation, what the Step 2
descriptive analysis suggested: confidence and spread do not contribute
meaningful, statistically defensible predictive power in this model — the
classifier is effectively a 1-feature model (`score_pct` alone) wearing a
3-feature formula.**

---

## 3. Cross-validated performance

**Method:** 5-fold stratified cross-validation — the data is split into 5
folds; for each fold, the model is refit on the other 4 folds and used to
predict the held-out fold, so every essay gets a prediction from a model
that never saw it during training. This avoids the inflated-accuracy
problem of testing a model on the same data it was fit on.

**Formula — exact-match accuracy:**

```
exact_accuracy = (1/n) × Σ[ 1 if predicted_band_i == true_band_i else 0 ]
```

**Formula — adjacent-band agreement** (predicted band is the true band or
one band away, treating Poor < Fair < Good < Excellent as ordered
positions 0-3):

```
adjacent_agreement = (1/n) × Σ[ 1 if |position(predicted_i) − position(true_i)| ≤ 1 else 0 ]
```

| Metric | Value |
|---|---|
| n | 500 |
| **Exact-match accuracy** | **35.80%** |
| Adjacent-band agreement | 89.20% |

**Confusion matrix** (rows = true band, columns = predicted band):

| True \ Predicted | Poor | Fair | Good | Excellent |
|---|---|---|---|---|
| Poor | 2 | 102 | 15 | 0 |
| Fair | 3 | 151 | 28 | 0 |
| Good | 0 | 122 | 26 | 0 |
| Excellent | 0 | 39 | 12 | 0 |

**Per-band recall** (correct predictions ÷ actual count of that band):

| Band | Recall |
|---|---|
| Poor | 2/119 = **1.7%** |
| Fair | 151/182 = **83.0%** |
| Good | 26/148 = **17.6%** |
| Excellent | 0/51 = **0.0%** |

---

## 4. The critical, honest finding: compare against a trivial baseline

**Formula — majority-class baseline** (a "model" that ignores every input
feature and always predicts whichever band is most common in the data):

```
majority_baseline_accuracy = max(class_count) / n
```

| Baseline | Accuracy |
|---|---|
| Majority-class baseline (always guess "Fair") | **36.40%** (182/500) |
| **Trained classifier (5-fold CV)** | **35.80%** |
| Naive raw-score thresholding (Step 2, no trained model) | 33.60% |

**The trained classifier performs slightly *worse* than trivially always
guessing the most common band, and only marginally better than naive raw
score thresholding.** Looking at the confusion matrix explains why: the
model overwhelmingly predicts "Fair" or "Good" for almost every essay
regardless of its true band — it correctly identifies only 2 of 119 Poor
essays, and (like the naive baseline in Step 2) **never once predicts
Excellent, even for a single one of the 51 truly-Excellent essays.**

**Why this happened, tied back to earlier findings:**
1. `score_pct` is the only significant predictor, and Step 2 already showed
   the AI's raw score is compressed and biased — it never even reaches the
   naive 90% "Excellent" cutoff for any essay in the entire dataset. A model
   built on top of a score that structurally cannot distinguish "Good" from
   "Excellent" cannot learn to make that distinction either, no matter how
   it's trained.
2. `confidence` and `spread` — the two features that could have added
   independent signal beyond the biased raw score — turned out to be
   statistically non-significant, so they contribute essentially nothing to
   correct for this.
3. The adjacent-band agreement (89.2%) looks good in isolation, but is
   inflated by the ordinal structure itself: since bands are ordered and
   adjacent-agreement tolerates being one band off, and most essays cluster
   in the middle two bands (Fair/Good = 66% of the data), a model that
   mostly predicts "Fair or Good" will score well on this looser metric
   almost by construction — it should be reported alongside exact accuracy
   and the majority baseline, never alone.

---

## 5. What this means for the thesis

This is a legitimate, fully-evaluated result — not a failed run. The panel's
requirement was to build and evaluate an explicit, computable classification
model, which this satisfies rigorously (real formula, real coefficients,
real cross-validated evaluation). The honest conclusion the data supports
is:

> **In this DREsS-based evaluation, the trained ordinal classifier did not
> outperform a trivial majority-class baseline, because its only
> statistically significant input (the AI grader's raw score) is itself
> biased and compressed at the top end, and the other two inputs
> (confidence, spread) did not contribute statistically significant
> additional signal.**

This should be reported as a finding, not hidden. It also directly
motivates a concrete, well-supported recommendation for future work: the
grading-prompt calibration issue flagged back in Step 2 (the AI's
systematic −7-point bias, and its raw score never reaching the Excellent
range) is very likely the root cause limiting the classifier's ceiling —
not the classifier's own methodology. Correcting that bias first (before
training a classifier on top of it) is the most well-evidenced next step,
should time allow.

---

## Files
- Trained on: `classification_model/dress_data/dress_training_combined.csv` (gitignored, DREsS content)
- This results file: aggregate statistics only, safe to commit
