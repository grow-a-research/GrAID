"""
run_fewshot_test.py — small test of the few-shot worked-examples prompt
addition, re-grading a stratified subset of already-graded essays (paired
comparison: same essays, same professor ground truth, only the prompt
differs) against the current prompt (calibration + confidence fix, no
few-shot).

Kept small (20 essays, 5 per band) given the few-shot block roughly
doubles-to-triples token cost per call.

Run from repo root, GROQ_API_KEY set:

    python -m classification_model.run_fewshot_test
"""

import time
from pathlib import Path

import pandas as pd

from .classification_model import get_ai_features_for_essay
from .dress_pipeline import MAX_TOTAL_POINTS, build_dress_rubric_criteria_json, load_dress_bulk
from .few_shot_examples import _ORDER as EXEMPLAR_IDS
from .few_shot_examples import build_few_shot_block

N_PER_BAND = 5
SEED = 11

PROGRESS_PATH = Path(__file__).resolve().parent / "dress_data" / "fewshot_test_result.csv"
PROGRESS_COLUMNS = ["essay_id", "prof_band", "prof_score_pct", "old_ai_score_pct", "new_ai_score_pct", "new_confidence"]


def load_progress() -> pd.DataFrame:
    if PROGRESS_PATH.exists():
        return pd.read_csv(PROGRESS_PATH)
    return pd.DataFrame(columns=PROGRESS_COLUMNS)


def append_progress(row: dict) -> None:
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    is_new = not PROGRESS_PATH.exists()
    pd.DataFrame([row], columns=PROGRESS_COLUMNS).to_csv(PROGRESS_PATH, mode="a", header=is_new, index=False)


def main():
    old = pd.read_csv("classification_model/dress_data/full_200_professor_training.csv")
    bulk = load_dress_bulk()

    # Exclude the 4 exemplar essays themselves from the test set — testing on
    # essays the model was already "shown" would bias results optimistically.
    pool = old[~old["essay_id"].isin(EXEMPLAR_IDS)]
    subset_ids = pd.concat([
        pool[pool["prof_band_recal"] == band].sample(
            n=min(N_PER_BAND, (pool["prof_band_recal"] == band).sum()), random_state=SEED
        )
        for band in pool["prof_band_recal"].unique()
    ], ignore_index=True)
    subset = subset_ids.merge(bulk[["essay_id", "question_prompt", "essay_text"]], on="essay_id", how="left")

    progress_df = load_progress()
    done_ids = set(progress_df["essay_id"])
    remaining = subset[~subset["essay_id"].isin(done_ids)]
    print(f"Already done: {len(done_ids)}  Remaining: {len(remaining)}")

    if remaining.empty:
        print("Fully processed — see results below.")
    else:
        print(f"Re-grading {len(remaining)} essays with few-shot examples added...\n")
        rubric_json = build_dress_rubric_criteria_json()
        few_shot_block = build_few_shot_block()
        start = time.time()
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
                "essay_id": row["essay_id"],
                "prof_band": row["prof_band_recal"],
                "prof_score_pct": row["prof_score_pct"],
                "old_ai_score_pct": row["ai_score_pct"],
                "new_ai_score_pct": features.score_pct,
                "new_confidence": features.confidence,
            })
            elapsed = time.time() - start
            print(f"[{i}/{len(remaining)}] {row['essay_id']} ({row['prof_band_recal']}): "
                  f"old={row['ai_score_pct']:.1f} new={features.score_pct:.1f} "
                  f"prof={row['prof_score_pct']:.1f}  (elapsed {elapsed:.0f}s)")

    result = load_progress()
    if len(result) < len(subset):
        print(f"\n{len(result)}/{len(subset)} done — re-run this same command to continue.")
        if result.empty:
            return

    print("\n=== Without few-shot (existing data) ===")
    old_diff = result["old_ai_score_pct"] - result["prof_score_pct"]
    print(f"Bias: {old_diff.mean():.2f}   Corr with prof: {result['old_ai_score_pct'].corr(result['prof_score_pct']):.3f}")

    print("\n=== With few-shot examples ===")
    new_diff = result["new_ai_score_pct"] - result["prof_score_pct"]
    print(f"Bias: {new_diff.mean():.2f}   Corr with prof: {result['new_ai_score_pct'].corr(result['prof_score_pct']):.3f}")

    print(f"\nSaved full comparison to classification_model/dress_data/fewshot_test_result.csv")


if __name__ == "__main__":
    main()
