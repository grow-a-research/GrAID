"""
run_replacement_28_ai_grading.py — grades the 28 replacement essays
(selected in build_replacement_28_workbook.py) with the AI grader, using
the same few-shot + calibration prompt used for the current final
200-essay dataset. Doesn't need to wait for professor grading — this half
can run any time; the two get merged once professor scores come back.

Resumable, same pattern as every other runner in this project.

Usage (run from repo root, GROQ_API_KEY set):

    python -m classification_model.run_replacement_28_ai_grading
"""

from pathlib import Path

import pandas as pd

from .classification_model import get_ai_features_for_essay
from .dress_pipeline import MAX_TOTAL_POINTS, build_dress_rubric_criteria_json, load_dress_bulk
from .few_shot_examples import build_few_shot_block

IDS_PATH = Path(__file__).resolve().parent / "dress_data" / "replacement_28_ids.txt"
PROGRESS_PATH = Path(__file__).resolve().parent / "dress_data" / "replacement_28_ai_progress.csv"
PROGRESS_COLUMNS = ["essay_id", "ai_score_pct", "ai_confidence", "ai_spread"]


def load_progress() -> pd.DataFrame:
    if PROGRESS_PATH.exists():
        return pd.read_csv(PROGRESS_PATH)
    return pd.DataFrame(columns=PROGRESS_COLUMNS)


def append_progress(row: dict) -> None:
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    is_new = not PROGRESS_PATH.exists()
    pd.DataFrame([row], columns=PROGRESS_COLUMNS).to_csv(PROGRESS_PATH, mode="a", header=is_new, index=False)


def main():
    essay_ids = IDS_PATH.read_text().strip().splitlines()
    bulk = load_dress_bulk()
    essays = bulk[bulk["essay_id"].isin(essay_ids)][["essay_id", "question_prompt", "essay_text"]]
    print(f"Loaded {len(essays)} replacement essays to grade")

    progress_df = load_progress()
    done_ids = set(progress_df["essay_id"])
    remaining = essays[~essays["essay_id"].isin(done_ids)]
    print(f"Already done: {len(done_ids)}  Remaining: {len(remaining)}")

    if remaining.empty:
        print("Fully processed.")
        return

    rubric_json = build_dress_rubric_criteria_json()
    few_shot_block = build_few_shot_block()
    for i, (_, row) in enumerate(remaining.iterrows(), start=1):
        try:
            features = get_ai_features_for_essay(
                essay_id=row["essay_id"],
                question_prompt=row["question_prompt"],
                rubric_criteria_json=rubric_json,
                max_points=MAX_TOTAL_POINTS,
                essay_text=row["essay_text"],
                clean_text=True,
                few_shot_examples=few_shot_block,
            )
        except Exception as e:
            print(f"[{i}/{len(remaining)}] {row['essay_id']}: FAILED ({e}) — skipping, will retry next run")
            continue

        append_progress({
            "essay_id": features.essay_id,
            "ai_score_pct": features.score_pct,
            "ai_confidence": features.confidence,
            "ai_spread": features.spread,
        })
        print(f"[{i}/{len(remaining)}] {features.essay_id}: AI={features.score_pct:.1f}")

    total_done = len(load_progress())
    print(f"\nDone. Progress: {total_done}/{len(essays)}")
    if total_done < len(essays):
        print("Re-run this same command to continue.")
    else:
        print("Complete! Ready to merge once professor scores for these 28 come back.")


if __name__ == "__main__":
    main()
