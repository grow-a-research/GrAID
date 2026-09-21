"""
band_classifier.py — suggests a performance band (Poor / Fair / Good /
Excellent) for an AI-graded essay, using the ordinal logistic regression
trained in classification_model/ (see classification_model.py and
build_final_200_dataset.py).

The trained weights and cutoffs are hard-coded below so the live app needs
no statsmodels dependency and never retrains at runtime. If the model is
retrained, copy the new values in and bump MODEL_VERSION.

EXPERIMENTAL: the model was fitted on DREsS_New essays graded with few-shot
examples and the clean-text calibration note, neither of which the live
grading path uses. Live AI scores may be distributed differently, so the band
is a suggestion for the teacher, pending the live-system evaluation.
"""

import json
import math
from dataclasses import dataclass

MODEL_VERSION = "ordinal-logit-2026-09-17"

BAND_ORDER = ["Poor", "Fair", "Good", "Excellent"]

# z = W_SCORE_PCT * score_pct + W_CONFIDENCE * confidence + W_SPREAD * spread
W_SCORE_PCT = 0.1024999162198784
W_CONFIDENCE = 8.15492215588296
W_SPREAD = 0.004377484244233087

# Cutoffs on the z scale: Poor/Fair, Fair/Good, Good/Excellent.
CUTOFFS = (12.460324548337258, 13.663555405190419, 15.163743815738577)


@dataclass
class BandResult:
    band: str
    probabilities: dict[str, float]   # band -> probability, sums to 1
    spread: float


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def band_probabilities(score_pct: float, confidence: float, spread: float) -> dict[str, float]:
    z = W_SCORE_PCT * score_pct + W_CONFIDENCE * confidence + W_SPREAD * spread
    cumulative = [_sigmoid(c - z) for c in CUTOFFS] + [1.0]   # P(band <= each band)
    probs, prev = {}, 0.0
    for band, cum in zip(BAND_ORDER, cumulative):
        probs[band] = cum - prev
        prev = cum
    return probs


def criteria_spread(criteria_scores: list[dict]) -> float | None:
    """Highest minus lowest criterion percentage; None if fewer than 2 scorable criteria."""
    pcts = [c["score"] / c["max_points"] * 100 for c in criteria_scores if c.get("max_points")]
    return max(pcts) - min(pcts) if len(pcts) > 1 else None


def classify_essay(
    ai_score: float | None,
    max_points: float | None,
    confidence: float | None,
    criteria_scores_json: str | None,
) -> BandResult | None:
    """
    Suggest a band from a graded essay's stored results. Returns None when a
    band can't be computed honestly: no per-criterion breakdown (free-text
    rubric), fewer than 2 criteria, or missing score/max/confidence.
    """
    if ai_score is None or not max_points or confidence is None or not criteria_scores_json:
        return None
    try:
        criteria = json.loads(criteria_scores_json)
    except (TypeError, ValueError):
        return None
    spread = criteria_spread(criteria)
    if spread is None:
        return None
    probs = band_probabilities(ai_score / max_points * 100, confidence, spread)
    return BandResult(band=max(probs, key=probs.get), probabilities=probs, spread=spread)
