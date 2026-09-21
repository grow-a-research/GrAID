"""
run_calibration_test.py — small paired before/after test of the calibration
+ confidence prompt fix, re-grading a stratified subset of ALREADY-GRADED
essays so the comparison is apples-to-apples (same essays, same ground
truth, only the prompt differs).

Selects 10 essays per band (40 total, weighted toward checking whether
Excellent essays can now score higher) from the already-completed
500-essay run, re-grades them with the updated prompt (calibration note +
confidence note, both under clean_text=True), and reports old vs. new
score/bias/correlation on this identical subset.

This does NOT touch dress_training_combined.csv or any shard file — it's a
read-only comparison. Run from repo root, GROQ_API_KEY set:

    python -m classification_model.run_calibration_test
"""

import time

import pandas as pd

from .classification_model import get_ai_features_for_essay
from .dress_pipeline import MAX_TOTAL_POINTS, build_dress_rubric_criteria_json, load_dress_bulk

N_PER_BAND = 10
SEED = 7


def main():
    old = pd.read_csv("classification_model/dress_data/dress_training_combined.csv")
    bulk = load_dress_bulk()

    # Stratified subset: N_PER_BAND essays per band from the already-graded set
    subset_ids = pd.concat([
        old[old["gt_band"] == band].sample(n=min(N_PER_BAND, (old["gt_band"] == band).sum()), random_state=SEED)
        for band in old["gt_band"].unique()
    ], ignore_index=True)
    subset = subset_ids.merge(bulk[["essay_id", "question_prompt", "essay_text"]], on="essay_id", how="left")
    print(f"Re-grading {len(subset)} essays ({subset['gt_band'].value_counts().to_dict()}) with the updated prompt...\n")

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
            "gt_band": row["gt_band"],
            "gt_score_pct": row["gt_score_pct"],
            "old_score_pct": row["score_pct"],
            "new_score_pct": features.score_pct,
            "old_confidence": row["confidence"],
            "new_confidence": features.confidence,
        })
        elapsed = time.time() - start
        print(f"[{i}/{len(subset)}] {row['essay_id']} ({row['gt_band']}): "
              f"old={row['score_pct']:.1f} new={features.score_pct:.1f} gt={row['gt_score_pct']:.1f}  "
              f"(elapsed {elapsed:.0f}s)")

    result = pd.DataFrame(rows)
    result.to_csv("classification_model/dress_data/calibration_test_result.csv", index=False)

    print("\n=== Old prompt (on this subset) ===")
    old_diff = result["old_score_pct"] - result["gt_score_pct"]
    print(f"Bias: {old_diff.mean():.2f}   Corr with GT: {result['old_score_pct'].corr(result['gt_score_pct']):.3f}")
    print(f"Max old_score_pct among Excellent-band essays: "
          f"{result[result['gt_band']=='Excellent']['old_score_pct'].max():.1f}")

    print("\n=== New prompt (calibration + confidence fix) ===")
    new_diff = result["new_score_pct"] - result["gt_score_pct"]
    print(f"Bias: {new_diff.mean():.2f}   Corr with GT: {result['new_score_pct'].corr(result['gt_score_pct']):.3f}")
    print(f"Max new_score_pct among Excellent-band essays: "
          f"{result[result['gt_band']=='Excellent']['new_score_pct'].max():.1f}")
    print(f"Any Excellent-band essay now scoring >=90%: "
          f"{(result[result['gt_band']=='Excellent']['new_score_pct'] >= 90).sum()} / "
          f"{(result['gt_band']=='Excellent').sum()}")

    print(f"\nConfidence range — old: {result['old_confidence'].min():.3f}-{result['old_confidence'].max():.3f}  "
          f"new: {result['new_confidence'].min():.3f}-{result['new_confidence'].max():.3f}")

    print("\nSaved full comparison to classification_model/dress_data/calibration_test_result.csv")


if __name__ == "__main__":
    main()
