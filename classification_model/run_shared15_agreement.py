"""
run_shared15_agreement.py — grades all 15 shared-subset DREsS essays fresh
(under the current, improved clean_text=True prompt) and computes the real
Essay Score Agreement metric: AI vs. YOUR PROFESSORS' consensus scores, not
DREsS's own scores.

Re-grades all 15 (not just the 12 missing) so every essay uses the SAME
prompt version — the 3 already in dress_training_combined.csv were graded
under the OLDER prompt (before the calibration fix), and mixing prompt
versions in one comparison would be inconsistent.

Professor scores come from the Excel file you filled in
(dress_shared_scores_entry.xlsx pattern) — path overridable via the
PROFESSOR_SCORES_XLSX env var since it lives outside the repo.

Run from repo root, GROQ_API_KEY set:

    python -m classification_model.run_shared15_agreement
"""

import os
import time

import openpyxl
import pandas as pd

from .classification_model import get_ai_features_for_essay, score_to_band
from .dress_pipeline import MAX_TOTAL_POINTS, build_dress_rubric_criteria_json, load_dress_bulk

SHARED_15 = [
    "DRESS-1790", "DRESS-1781", "DRESS-1779", "DRESS-1777", "DRESS-1432",
    "DRESS-2151", "DRESS-1450", "DRESS-1685", "DRESS-1778", "DRESS-1449",
    "DRESS-1412", "DRESS-1664", "DRESS-1652", "DRESS-1433", "DRESS-2193",
]

DEFAULT_XLSX_PATH = r"C:\Users\ASUS\Downloads\DREsS Score .xlsx"
XLSX_PATH = os.environ.get("PROFESSOR_SCORES_XLSX", DEFAULT_XLSX_PATH)

OUT_PATH = "classification_model/dress_data/shared15_agreement_result.csv"


def load_professor_scores(xlsx_path: str) -> pd.DataFrame:
    """Total (/15) is column index 20, Overall % is column index 21."""
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb["Scores"]
    rows = list(ws.iter_rows(min_row=3, max_row=17, values_only=True))
    return pd.DataFrame([
        {"essay_id": r[0], "prof_total": r[20], "prof_pct": r[21]} for r in rows
    ])


def main():
    print(f"Loading professor scores from: {XLSX_PATH}")
    prof_df = load_professor_scores(XLSX_PATH)

    bulk = load_dress_bulk()
    dress_official = bulk[bulk["essay_id"].isin(SHARED_15)][
        ["essay_id", "question_prompt", "essay_text", "gt_score_pct", "gt_band"]
    ]

    subset = dress_official.merge(prof_df, on="essay_id", how="left")
    if subset["prof_pct"].isna().any():
        missing = subset[subset["prof_pct"].isna()]["essay_id"].tolist()
        raise ValueError(f"No professor score found for: {missing} — check essay_id spelling in the Excel file")

    print(f"Re-grading all {len(subset)} shared essays with the current prompt (clean_text=True)...\n")
    rubric_json = build_dress_rubric_criteria_json()
    rows = []
    start = time.time()
    for i, (_, row) in enumerate(subset.iterrows(), start=1):
        try:
            features = get_ai_features_for_essay(
                essay_id=row["essay_id"],
                question_prompt=row["question_prompt"],
                rubric_criteria_json=rubric_json,
                max_points=MAX_TOTAL_POINTS,
                essay_text=row["essay_text"],
                clean_text=True,
            )
        except Exception as e:
            print(f"[{i}/{len(subset)}] {row['essay_id']}: FAILED ({e}) — skipping")
            continue

        rows.append({
            "essay_id": row["essay_id"],
            "ai_pct": features.score_pct,
            "ai_confidence": features.confidence,
            "ai_spread": features.spread,
            "prof_pct": row["prof_pct"],
            "dress_pct": row["gt_score_pct"],
            "dress_band": row["gt_band"],
        })
        elapsed = time.time() - start
        print(f"[{i}/{len(subset)}] {row['essay_id']}: AI={features.score_pct:.1f}  "
              f"Prof={row['prof_pct']:.1f}  DREsS={row['gt_score_pct']:.1f}  (elapsed {elapsed:.0f}s)")

    result = pd.DataFrame(rows)
    result.to_csv(OUT_PATH, index=False)
    print(f"\nSaved to {OUT_PATH}\n")

    def agreement_stats(a, b, label):
        diff = a - b
        a15, b15 = a / 100 * 15, b / 100 * 15
        within_1 = (a15 - b15).abs() <= 1.0
        print(f"=== {label} ===")
        print(f"  Bias (first - second): {diff.mean():.2f}")
        print(f"  Correlation: {a.corr(b):.3f}")
        print(f"  Essay Score Agreement (within 1pt/15): {within_1.mean()*100:.1f}%")
        print()

    agreement_stats(result["ai_pct"], result["prof_pct"], "AI vs. YOUR PROFESSORS (the real thesis metric)")
    agreement_stats(result["ai_pct"], result["dress_pct"], "AI vs. DREsS official scores")
    agreement_stats(result["prof_pct"], result["dress_pct"], "Your professors vs. DREsS official scores")


if __name__ == "__main__":
    main()
