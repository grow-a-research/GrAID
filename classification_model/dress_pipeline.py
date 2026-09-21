"""
dress_pipeline.py — DREsS_New-only training path for the essay
rubric-band classifier.

Bypasses professor_grades.csv entirely: DREsS_New.tsv already carries its
own expert-assigned Content/Organization/Language scores, which are used
directly as ground truth. No professor grading and no OCR/scanning is
needed for this path — DREsS essays are already digital text, fed
straight into ai_grader.grade_essay() as-is.

DREsS_New.tsv itself lives OUTSIDE this repo and must stay there — the
dataset's own README prohibits personal sharing, and this repo is public.
Point DRESS_TSV_PATH (or pass tsv_path explicitly) at wherever it's kept
locally; nothing in this module copies its contents into a repo-tracked
file.
"""

from __future__ import annotations

import json
import os

import pandas as pd

from .classification_model import AIFeatures, get_ai_features_for_essay, score_to_band

# Overridable via the DRESS_TSV_PATH environment variable, since this path is
# machine-specific — e.g. a teammate running their own shard on their own
# machine will have DREsS_New.tsv somewhere else.
DRESS_TSV_PATH = os.environ.get(
    "DRESS_TSV_PATH",
    r"C:\Users\ASUS\OneDrive\Desktop\Files\John\DREsS_Case\DREsS_New.tsv",
)
MIN_WORDS = 150
CRITERION_MAX_POINTS = 5

# Level descriptions adapted from DREsS's own rubric (Yoo et al., ACL 2025,
# Table 2) — see classification_model/dress_shared_rubric.md for the source
# and the norming caveat (not yet validated with professors, N/A for this
# DREsS-only path since DREsS's own scores are the ground truth here).
RUBRIC_CRITERIA = [
    {
        "name": "Content",
        "max_points": CRITERION_MAX_POINTS,
        "levels": [
            {"label": "5", "points": 5, "description": "Well-developed, clearly relevant argument; strong, specific reasons and examples throughout"},
            {"label": "4", "points": 4, "description": "Mostly developed and relevant; reasons/examples present but under-elaborated in places"},
            {"label": "3", "points": 3, "description": "Argument present but development is inconsistent; some reasons/examples generic or thin"},
            {"label": "2", "points": 2, "description": "Argument unclear or weakly related to the prompt; few or unconvincing supporting reasons/examples"},
            {"label": "1", "points": 1, "description": "Little to no relevant argument; supporting reasons/examples missing or off-topic"},
        ],
    },
    {
        "name": "Organization",
        "max_points": CRITERION_MAX_POINTS,
        "levels": [
            {"label": "5", "points": 5, "description": "Very effective structure, easy to follow, strong coherence devices, one main idea per paragraph"},
            {"label": "4", "points": 4, "description": "Generally well-structured and easy to follow; minor coherence or paragraph-focus lapses"},
            {"label": "3", "points": 3, "description": "Structure discernible but uneven; some ideas hard to follow or paragraphs mix multiple ideas"},
            {"label": "2", "points": 2, "description": "Weak structure; confusing sequencing of ideas; coherence devices rare or misused"},
            {"label": "1", "points": 1, "description": "Little discernible structure; ideas appear disconnected or randomly ordered"},
        ],
    },
    {
        "name": "Language",
        "max_points": CRITERION_MAX_POINTS,
        "levels": [
            {"label": "5", "points": 5, "description": "Sophisticated, varied vocabulary and collocations; grammar/spelling/punctuation correct throughout"},
            {"label": "4", "points": 4, "description": "Good vocabulary range; occasional minor errors that don't impede understanding"},
            {"label": "3", "points": 3, "description": "Adequate vocabulary; noticeable errors, occasionally distracting"},
            {"label": "2", "points": 2, "description": "Limited vocabulary; frequent errors that sometimes obscure meaning"},
            {"label": "1", "points": 1, "description": "Very limited vocabulary; pervasive errors that significantly impede understanding"},
        ],
    },
]

MAX_TOTAL_POINTS = sum(c["max_points"] for c in RUBRIC_CRITERIA)  # 15


def build_dress_rubric_criteria_json() -> str:
    """rubric_criteria_json for DREsS's own Content/Organization/Language rubric."""
    return json.dumps(RUBRIC_CRITERIA)


def load_dress_bulk(tsv_path: str = DRESS_TSV_PATH, min_words: int = MIN_WORDS) -> pd.DataFrame:
    """
    Load DREsS_New.tsv and build the ground-truth table directly from its
    own Content/Organization/Language scores — no professor_grades.csv
    involved.

    Ground truth is recomputed as content+organization+language rather
    than trusting the file's own `total` column, which is missing for
    ~167 rows and, elsewhere in the file, occasionally off by up to 2
    points from the sum of the three criteria.
    """
    df = pd.read_csv(tsv_path, sep="\t")
    required = {"id", "prompt", "essay", "content", "organization", "language"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"DREsS_New.tsv is missing expected columns: {missing}")

    word_count = df["essay"].str.split().str.len()
    df = df[word_count >= min_words].copy()

    df["essay_id"] = "DRESS-" + df["id"].astype(str)
    df["gt_score_pct"] = (df["content"] + df["organization"] + df["language"]) / MAX_TOTAL_POINTS * 100
    df["gt_band"] = df["gt_score_pct"].apply(score_to_band)

    return df.rename(columns={"prompt": "question_prompt", "essay": "essay_text"})[
        ["essay_id", "question_prompt", "essay_text", "gt_score_pct", "gt_band"]
    ]


def select_stratified_sample(dress_df: pd.DataFrame, n: int, seed: int = 42) -> pd.DataFrame:
    """
    Draw a stratified random sample of size n from dress_df, proportional to
    the real gt_band distribution (Poor/Fair/Good/Excellent) rather than
    equal-per-class, so the sample stays representative of the population.

    Deterministic given the same seed — document the seed in the
    methodology so the exact sample is reproducible.
    """
    band_counts = dress_df["gt_band"].value_counts()
    proportions = band_counts / band_counts.sum()
    per_band_n = (proportions * n).round().astype(int)

    # Rounding can drift the total off n by a couple rows either way — patch
    # the largest band so the sample size is exactly n.
    drift = n - per_band_n.sum()
    if drift != 0:
        largest_band = per_band_n.idxmax()
        per_band_n[largest_band] += drift

    parts = [
        dress_df[dress_df["gt_band"] == band].sample(n=count, random_state=seed)
        for band, count in per_band_n.items()
        if count > 0
    ]
    return pd.concat(parts, ignore_index=True)


def get_ai_features_for_dress(dress_df: pd.DataFrame, limit: int | None = None) -> list[AIFeatures]:
    """
    Run each DREsS essay through the real AI grader to get its
    score_pct/confidence/spread. Each call hits the live Groq API — pass
    `limit` to run a small batch first rather than the full set. Requires
    GROQ_API_KEY to be set.
    """
    rubric_json = build_dress_rubric_criteria_json()
    rows = dress_df.head(limit) if limit else dress_df
    features = []
    for _, row in rows.iterrows():
        features.append(get_ai_features_for_essay(
            essay_id=row["essay_id"],
            question_prompt=row["question_prompt"],
            rubric_criteria_json=rubric_json,
            max_points=MAX_TOTAL_POINTS,
            essay_text=row["essay_text"],
            clean_text=True,
        ))
    return features


def assemble_training_table_from_dress(
    dress_df: pd.DataFrame, ai_features: list[AIFeatures],
) -> pd.DataFrame:
    """
    Merge AI features with DREsS's own ground truth. Produces the same
    column shape as classification_model.assemble_training_table()'s
    output (score_pct, confidence, spread, gt_score_pct, gt_band), so it
    plugs directly into train_ordinal_classifier()/cross_validate()
    without any changes to those functions.
    """
    ai_df = pd.DataFrame([vars(f) for f in ai_features])
    table = ai_df.merge(dress_df[["essay_id", "gt_score_pct", "gt_band"]], on="essay_id", how="inner")
    if len(table) < len(ai_df):
        missing = set(ai_df["essay_id"]) - set(table["essay_id"])
        raise ValueError(f"No DREsS ground truth found for essays: {missing}")
    return table
