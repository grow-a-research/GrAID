"""
holistic_pipeline.py — holistic (single overall score, no per-criterion
breakdown) grading path for comparison against the analytic/structured
path already used throughout this project.

Reuses the same DREsS rubric definition (dress_pipeline.RUBRIC_CRITERIA),
just flattened into descriptive text via ai_grader's own helper, and
routes through ai_grader.grade_essay()'s existing holistic fallback
(rubric_criteria_json=None) rather than building a new grading path.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_grader import _render_criteria_for_prompt, grade_essay

from .dress_pipeline import MAX_TOTAL_POINTS, RUBRIC_CRITERIA


def build_flattened_rubric_text() -> str:
    """Same rubric as the structured path, rendered as flat descriptive text."""
    return _render_criteria_for_prompt(RUBRIC_CRITERIA)


@dataclass
class HolisticFeatures:
    essay_id: str
    score_pct: float
    confidence: float


def get_holistic_features_for_essay(
    essay_id: str,
    question_prompt: str,
    rubric_text: str,
    max_points: float,
    essay_text: str,
) -> HolisticFeatures:
    """
    Run one essay through the holistic grading path (single overall score).
    clean_text=True always — this is only ever used for DREsS essays.
    """
    result = grade_essay(
        question_prompt=question_prompt,
        rubric_text=rubric_text,
        rubric_criteria_json=None,
        max_points=max_points,
        ocr_text=essay_text,
        clean_text=True,
    )
    return HolisticFeatures(
        essay_id=essay_id,
        score_pct=result.score / max_points * 100,
        confidence=result.confidence,
    )
