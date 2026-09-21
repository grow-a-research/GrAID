"""
run_anticompression_test.py — small paired test of the anti-compression note
(few_shot_examples.ANTI_COMPRESSION_NOTE), re-grading a stratified subset of
the already-graded 200 essays with that note appended to the existing
few-shot block, and comparing bias-by-band against the known baseline
(fewshot_full_combined.csv — the current few-shot-only prompt, no
anti-compression note).

"Old" values are NOT re-fetched — they're read straight from
fewshot_full_combined.csv for the exact same essay_ids, since that's the
real, already-paid-for measurement of the current prompt's bias. Only the
"new" (anti-compression) side costs fresh API calls.

Run from repo root, GROQ_API_KEY set:

    python -m classification_model.run_anticompression_test
"""

import time
from pathlib import Path

import pandas as pd

from .classification_model import get_ai_features_for_essay
from .dress_pipeline import MAX_TOTAL_POINTS, build_dress_rubric_criteria_json, load_dress_bulk
from .few_shot_examples import ANTI_COMPRESSION_NOTE, _ORDER as EXEMPLAR_IDS, build_few_shot_block

N_PER_BAND = 6
SEED = 23

PROGRESS_PATH = Path(__file__).resolve().parent / "dress_data" / "anticompression_test_result.csv"
PROGRESS_COLUMNS = ["essay_id", "gt_band", "prof_score_pct", "old_ai_score_pct", "new_ai_score_pct", "new_confidence"]


def load_progress() -> pd.DataFrame:
    if PROGRESS_PATH.exists():
        return pd.read_csv(PROGRESS_PATH)
    return pd.DataFrame(columns=PROGRESS_COLUMNS)


def append_progress(row: dict) -> None:
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    is_new = not PROGRESS_PATH.exists()
    pd.DataFrame([row], columns=PROGRESS_COLUMNS).to_csv(PROGRESS_PATH, mode="a", header=is_new, index=False)


def main():
    combined = pd.read_csv("classification_model/dress_data/fewshot_full_combined.csv").rename(
        columns={"ai_score_pct": "old_ai_score_pct", "prof_band_recal": "gt_band"}
    )
    bulk = load_dress_bulk()

    # Exclude the 4 exemplar essays themselves — testing on essays the model
    # was already "shown" would bias results optimistically.
    pool = combined[~combined["essay_id"].isin(EXEMPLAR_IDS)]
    subset = pd.concat([
        pool[pool["gt_band"] == band].sample(
            n=min(N_PER_BAND, (pool["gt_band"] == band).sum()), random_state=SEED
        )
        for band in pool["gt_band"].unique()
    ], ignore_index=True)
    subset = subset.merge(bulk[["essay_id", "question_prompt", "essay_text"]], on="essay_id", how="left")

    progress_df = load_progress()
    done_ids = set(progress_df["essay_id"])
    remaining = subset[~subset["essay_id"].isin(done_ids)]
    print(f"Already done: {len(done_ids)}  Remaining: {len(remaining)}")

    if remaining.empty:
        print("Fully processed — see results below.")
    else:
        print(f"Re-grading {len(remaining)} essays with the anti-compression note added...\n")
        rubric_json = build_dress_rubric_criteria_json()
        few_shot_block = build_few_shot_block() + ANTI_COMPRESSION_NOTE
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
                "gt_band": row["gt_band"],
                "prof_score_pct": row["prof_score_pct"],
                "old_ai_score_pct": row["old_ai_score_pct"],
                "new_ai_score_pct": features.score_pct,
                "new_confidence": features.confidence,
            })
            elapsed = time.time() - start
            print(f"[{i}/{len(remaining)}] {row['essay_id']} ({row['gt_band']}): "
                  f"old={row['old_ai_score_pct']:.1f} new={features.score_pct:.1f} "
                  f"prof={row['prof_score_pct']:.1f}  (elapsed {elapsed:.0f}s)")

    result = load_progress()
    if len(result) < len(subset):
        print(f"\n{len(result)}/{len(subset)} done — re-run this same command to continue.")
        if result.empty:
            return

    print("\n=== Bias by band: current few-shot (no anti-compression) ===")
    for band in sorted(result["gt_band"].unique()):
        sub = result[result["gt_band"] == band]
        bias = (sub["old_ai_score_pct"] - sub["prof_score_pct"]).mean()
        print(f"  {band}: n={len(sub)}  bias={bias:+.2f}")
    old_corr = result["old_ai_score_pct"].corr(result["prof_score_pct"])
    print(f"  Correlation: {old_corr:.3f}")

    print("\n=== Bias by band: WITH anti-compression note ===")
    for band in sorted(result["gt_band"].unique()):
        sub = result[result["gt_band"] == band]
        bias = (sub["new_ai_score_pct"] - sub["prof_score_pct"]).mean()
        print(f"  {band}: n={len(sub)}  bias={bias:+.2f}")
    new_corr = result["new_ai_score_pct"].corr(result["prof_score_pct"])
    print(f"  Correlation: {new_corr:.3f}")

    print(f"\nSaved full comparison to {PROGRESS_PATH}")


if __name__ == "__main__":
    main()
