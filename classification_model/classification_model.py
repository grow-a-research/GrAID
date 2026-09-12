"""
classification_model.py — Essay rubric-level classification model.

Trains and evaluates an ordinal logistic regression that classifies an essay
into one of four rubric performance bands (Poor / Fair / Good / Excellent)
based on three signals already produced by the AI grader in ai_grader.py:
the AI's overall score (as a % of max points), its self-reported confidence,
and the spread (disagreement) across its per-criterion scores.

This is a separate, purpose-built classifier — it does not replace or alter
ai_grader.py's zero-shot rubric-conditioned grading. It exists to answer a
thesis-panel requirement for an explicit, trained classification model with
a computable formula, sitting alongside the existing AI grader.

--------------------------------------------------------------------------
Expected input data (once professor grades are collected)
--------------------------------------------------------------------------
A single CSV, long format, one row per (essay, criterion, professor):

    essay_id, part, professor_id, question_prompt, essay_text,
    criterion_name, criterion_max_points, criterion_score

  - part: 1 (own-class essay, single rater) or 2 (shared PERSUADE batch,
    graded by all 5 professors — multiple rows per essay, one per professor)
  - essay_text: the plain text of the essay (typed for Part 2, OCR'd text
    for Part 1)

See build_professor_grades_template() below for a ready-to-fill example.

--------------------------------------------------------------------------
Pipeline
--------------------------------------------------------------------------
1. load_professor_grades()      — read the CSV above
2. get_ai_features_for_essay()  — call ai_grader.grade_essay() per essay to
                                   get the AI's score/confidence/spread
3. assemble_training_table()    — merge AI features with ground-truth bands
                                   (averaging Part 2's multiple raters)
4. train_ordinal_classifier()   — fit with k-fold cross-validation
5. evaluate_predictions()       — accuracy, adjacent agreement, confusion
                                   matrix, reported against held-out folds
"""

from __future__ import annotations

import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedKFold
from statsmodels.miscmodels.ordinal_model import OrderedModel

# ai_grader.py lives at the repo root, one level up from this package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ai_grader import grade_essay

BAND_ORDER = ["Poor", "Fair", "Good", "Excellent"]

# Fixed percentage cutoffs used to convert a ground-truth (or AI) score % into
# a rubric performance band. Applied consistently across all professors'
# differing rubrics/point scales, since scores are normalized to % first.
BAND_CUTOFFS = {"Excellent": 90, "Good": 75, "Fair": 60}  # Poor = below Fair


def score_to_band(pct: float) -> str:
    """Classify a 0-100 percentage into a rubric performance band."""
    if pct >= BAND_CUTOFFS["Excellent"]:
        return "Excellent"
    if pct >= BAND_CUTOFFS["Good"]:
        return "Good"
    if pct >= BAND_CUTOFFS["Fair"]:
        return "Fair"
    return "Poor"


# ── Step 1: load professor grades ──────────────────────────────────────────

def load_professor_grades(csv_path: str) -> pd.DataFrame:
    """Load the long-format professor grades CSV described in the module docstring."""
    df = pd.read_csv(csv_path)
    required = {"essay_id", "part", "professor_id", "question_prompt",
                "essay_text", "criterion_name", "criterion_max_points", "criterion_score"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"professor_grades.csv is missing required columns: {missing}")
    return df


def build_professor_grades_template(out_path: str, n_example_rows: int = 6) -> None:
    """Write an empty, correctly-headed CSV template with a few example rows."""
    example = pd.DataFrame([
        {"essay_id": "E-001", "part": 1, "professor_id": "profA",
         "question_prompt": "Discuss the effects of distance learning.",
         "essay_text": "<essay text here>",
         "criterion_name": "Content", "criterion_max_points": 10, "criterion_score": 7},
        {"essay_id": "E-001", "part": 1, "professor_id": "profA",
         "question_prompt": "Discuss the effects of distance learning.",
         "essay_text": "<essay text here>",
         "criterion_name": "Organization", "criterion_max_points": 10, "criterion_score": 8},
        {"essay_id": "E-001", "part": 1, "professor_id": "profA",
         "question_prompt": "Discuss the effects of distance learning.",
         "essay_text": "<essay text here>",
         "criterion_name": "Grammar", "criterion_max_points": 10, "criterion_score": 6},
        {"essay_id": "PB-001", "part": 2, "professor_id": "profA",
         "question_prompt": "Summer projects.",
         "essay_text": "<PERSUADE batch essay text here>",
         "criterion_name": "Content", "criterion_max_points": 10, "criterion_score": 8},
        {"essay_id": "PB-001", "part": 2, "professor_id": "profB",
         "question_prompt": "Summer projects.",
         "essay_text": "<PERSUADE batch essay text here>",
         "criterion_name": "Content", "criterion_max_points": 10, "criterion_score": 7},
        {"essay_id": "PB-001", "part": 2, "professor_id": "profC",
         "question_prompt": "Summer projects.",
         "essay_text": "<PERSUADE batch essay text here>",
         "criterion_name": "Content", "criterion_max_points": 10, "criterion_score": 9},
    ][:n_example_rows])
    example.to_csv(out_path, index=False)


# ── Step 2: AI feature extraction (calls the real grading pipeline) ────────

def build_rubric_criteria_json(criteria: list[dict]) -> str:
    """
    Build the rubric_criteria_json string grade_essay() expects.

    criteria: list of {"name": str, "max_points": float, "levels": [
        {"label": str, "points": float, "description": str}, ...]}
    Each professor's real rubric (criteria + level descriptions) needs to be
    digitized into this structure once, ahead of time — it is not derivable
    from the professor_grades.csv scores alone.
    """
    return json.dumps(criteria)


@dataclass
class AIFeatures:
    essay_id: str
    score_pct: float
    confidence: float
    spread: float


def get_ai_features_for_essay(
    essay_id: str,
    question_prompt: str,
    rubric_criteria_json: str,
    max_points: float,
    essay_text: str,
) -> AIFeatures:
    """
    Run one essay through the existing AI grader (ai_grader.grade_essay) and
    reduce its per-criterion output to the 3 classifier inputs.

    Requires GROQ_API_KEY to be set (same as the rest of the system).
    """
    result = grade_essay(
        question_prompt=question_prompt,
        rubric_text=None,
        rubric_criteria_json=rubric_criteria_json,
        max_points=max_points,
        ocr_text=essay_text,
    )
    if not result.criteria_scores_json:
        raise RuntimeError(
            f"Essay {essay_id}: AI grading did not return per-criterion scores "
            "(structured grading failed and fell back to holistic). Cannot compute spread."
        )
    criteria_scores = json.loads(result.criteria_scores_json)
    pcts = [cs["score"] / cs["max_points"] * 100 for cs in criteria_scores if cs["max_points"]]
    spread = (max(pcts) - min(pcts)) if len(pcts) > 1 else 0.0
    overall_pct = result.score / max_points * 100
    return AIFeatures(essay_id=essay_id, score_pct=overall_pct,
                       confidence=result.confidence, spread=spread)


# ── Step 3: assemble the training table ─────────────────────────────────────

def assemble_training_table(
    professor_df: pd.DataFrame,
    ai_features: list[AIFeatures],
) -> pd.DataFrame:
    """
    Combine AI features with ground-truth bands.

    Part 1 essays: ground truth = the single professor's own score.
    Part 2 essays: ground truth = the average across all professors who
    graded that essay, per criterion, before converting to a band.
    """
    gt_pct = (
        professor_df
        .assign(pct=lambda d: d["criterion_score"] / d["criterion_max_points"] * 100)
        .groupby(["essay_id", "professor_id"])["pct"].mean()  # per-professor overall %
        .groupby("essay_id").mean()  # average across professors (no-op for Part 1's single rater)
        .rename("gt_score_pct")
        .reset_index()
    )
    gt_pct["gt_band"] = gt_pct["gt_score_pct"].apply(score_to_band)

    ai_df = pd.DataFrame([vars(f) for f in ai_features])
    table = ai_df.merge(gt_pct, on="essay_id", how="inner")
    if len(table) < len(ai_df):
        missing = set(ai_df["essay_id"]) - set(table["essay_id"])
        raise ValueError(f"No ground-truth grades found for essays: {missing}")
    return table


# ── Step 4: train the ordinal logistic regression ──────────────────────────

def train_ordinal_classifier(table: pd.DataFrame):
    """Fit the final ordinal logistic regression on the full training table."""
    y = pd.Series(pd.Categorical(table["gt_band"], categories=BAND_ORDER, ordered=True))
    X = table[["score_pct", "confidence", "spread"]]
    model = OrderedModel(y, X, distr="logit")
    result = model.fit(method="bfgs", disp=False)
    return model, result


def cross_validate(table: pd.DataFrame, n_splits: int = 5, seed: int = 42) -> pd.DataFrame:
    """
    K-fold cross-validation: train on k-1 folds, predict the held-out fold,
    repeated so every essay gets a prediction from a model that never saw it.
    Returns a DataFrame of essay_id, true band, predicted band.
    """
    y_labels = table["gt_band"].values
    X = table[["score_pct", "confidence", "spread"]].values
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)

    rows = []
    for train_idx, test_idx in skf.split(X, y_labels):
        train_df = table.iloc[train_idx].reset_index(drop=True)
        test_df = table.iloc[test_idx].reset_index(drop=True)

        y_train = pd.Series(pd.Categorical(train_df["gt_band"], categories=BAND_ORDER, ordered=True))
        X_train = train_df[["score_pct", "confidence", "spread"]]
        model = OrderedModel(y_train, X_train, distr="logit")
        result = model.fit(method="bfgs", disp=False)

        X_test = test_df[["score_pct", "confidence", "spread"]]
        probs = model.predict(result.params, exog=X_test)
        pred_idx = np.argmax(probs, axis=1)
        pred_bands = [BAND_ORDER[i] for i in pred_idx]

        for eid, true_band, pred_band in zip(test_df["essay_id"], test_df["gt_band"], pred_bands):
            rows.append({"essay_id": eid, "true_band": true_band, "predicted_band": pred_band})

    return pd.DataFrame(rows)


# ── Step 5: evaluation ───────────────────────────────────────────────────

def evaluate_predictions(cv_results: pd.DataFrame) -> dict:
    """Exact-match accuracy, adjacent-band agreement, and a confusion matrix."""
    idx = {b: i for i, b in enumerate(BAND_ORDER)}
    exact = cv_results["true_band"] == cv_results["predicted_band"]
    adjacent = (cv_results["true_band"].map(idx) - cv_results["predicted_band"].map(idx)).abs() <= 1

    confusion = pd.crosstab(cv_results["true_band"], cv_results["predicted_band"],
                             rownames=["True"], colnames=["Predicted"]) \
                  .reindex(index=BAND_ORDER, columns=BAND_ORDER, fill_value=0)

    return {
        "n": len(cv_results),
        "exact_accuracy": exact.mean(),
        "adjacent_agreement": adjacent.mean(),
        "confusion_matrix": confusion,
    }


def summarize_formula(result) -> str:
    """
    Human-readable printout of the trained formula's coefficients and cutoffs.

    NOTE: statsmodels' OrderedModel does not store threshold cutoffs directly
    in result.params past the first one — everything after the first
    threshold is an unconstrained log-increment over the previous cutoff (see
    OrderedModel.transform_threshold_params), so the raw params must be
    passed through that transform to get the actual z-score cutoffs. Printing
    result.params directly for thresholds 2+ silently reports the wrong
    numbers (right order of magnitude, wrong value).
    """
    p = result.params
    threshold_names = [name for name in p.index if name not in ("score_pct", "confidence", "spread")]
    thresholds = result.model.transform_threshold_params(p.values)[1:-1]  # drop -inf/+inf bounds

    lines = ["Trained formula:",
             f"  z = ({p['score_pct']:.4f} x Score%) + ({p['confidence']:.4f} x Confidence) "
             f"+ ({p['spread']:.4f} x Spread)",
             "Thresholds:"]
    for name, thresh in zip(threshold_names, thresholds):
        lines.append(f"  {name}: {thresh:.4f}")
    return "\n".join(lines)


# ── Demo / self-test with synthetic data (no professor data or API needed) ─

def _demo():
    """
    Runs the training + evaluation pipeline end-to-end on synthetic,
    made-up data, purely to verify the pipeline works correctly before
    real professor/AI data is available. Not real results.
    """
    rng = np.random.default_rng(7)
    n = 150
    score_pct = rng.uniform(20, 100, n)
    confidence = rng.uniform(0.4, 0.99, n)
    spread = rng.uniform(0, 45, n)
    # synthetic ground truth correlated with score_pct plus noise, so the
    # demo has a learnable (not random) relationship to verify against
    noisy_pct = np.clip(score_pct + rng.normal(0, 8, n), 0, 100)
    gt_band = [score_to_band(p) for p in noisy_pct]

    table = pd.DataFrame({
        "essay_id": [f"DEMO-{i:03d}" for i in range(n)],
        "score_pct": score_pct, "confidence": confidence, "spread": spread,
        "gt_band": gt_band,
    })

    print("=== DEMO: synthetic data, NOT real results ===\n")
    model, result = train_ordinal_classifier(table)
    print(summarize_formula(result), "\n")

    cv = cross_validate(table)
    metrics = evaluate_predictions(cv)
    print(f"Cross-validated exact accuracy:    {metrics['exact_accuracy']:.1%}")
    print(f"Cross-validated adjacent agreement: {metrics['adjacent_agreement']:.1%}")
    print("\nConfusion matrix (rows = true, cols = predicted):")
    print(metrics["confusion_matrix"])


if __name__ == "__main__":
    _demo()
