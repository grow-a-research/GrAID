"""
run_fewshot_full_retrain.py — combines the 7 sharded outputs of
run_fewshot_full.py into the final 200-essay few-shot dataset, attaches the
quartile-recalibrated ground-truth bands (same recalibration already used
for full_200_professor_training.csv — not the old DREsS-native 60/75/90
cutoffs baked into score_to_band()), retrains the ordinal classifier, and
reports the full-scale evaluation: 5-fold CV accuracy, majority baseline,
confusion matrix, coefficient significance, correlation, and bias-by-band.

Run from repo root:

    python -m classification_model.run_fewshot_full_retrain
"""

from pathlib import Path

import pandas as pd

from .classification_model import (
    BAND_ORDER,
    cross_validate,
    evaluate_predictions,
    summarize_formula,
    train_ordinal_classifier,
)

DATA_DIR = Path(__file__).resolve().parent / "dress_data"
N_SHARDS = 7
OLD_TRAINING_PATH = DATA_DIR / "full_200_professor_training.csv"
OUT_PATH = DATA_DIR / "fewshot_full_combined.csv"


def combine_shards() -> pd.DataFrame:
    dfs = [pd.read_csv(DATA_DIR / f"fewshot_full_progress_shard{i}.csv") for i in range(N_SHARDS)]
    combined = pd.concat(dfs, ignore_index=True)
    if combined["essay_id"].duplicated().any():
        dupes = combined[combined["essay_id"].duplicated(keep=False)]["essay_id"].unique()
        raise ValueError(f"Duplicate essay_ids across shards: {dupes}")
    return combined


def attach_recalibrated_bands(combined: pd.DataFrame) -> pd.DataFrame:
    """
    combined['prof_band'] uses the OLD DREsS-native cutoffs (60/75/90) from
    score_to_band() via professor_ground_truth.load_professor_consensus() —
    that band is stale (0 Excellent essays possible, since profs never
    scored above ~86.67%). The correct quartile-recalibrated bands
    (25th/50th/75th percentile of the 200 real professor scores) already
    exist per-essay in full_200_professor_training.csv as 'prof_band_recal'.
    Ground truth (prof_score_pct) is identical between the two files
    (verified byte-for-byte before this script was written) — only the AI
    features differ, since this is a re-grade with the few-shot prompt.
    """
    old = pd.read_csv(OLD_TRAINING_PATH)[["essay_id", "prof_score_pct", "prof_band_recal"]]
    merged = combined.merge(old, on="essay_id", how="left", suffixes=("", "_old"))

    mismatch = (merged["prof_score_pct"] - merged["prof_score_pct_old"]).abs() > 0.01
    if mismatch.any():
        raise ValueError(f"Ground-truth score mismatch for: {merged.loc[mismatch, 'essay_id'].tolist()}")
    if merged["prof_band_recal"].isna().any():
        raise ValueError(f"No recalibrated band found for: {merged.loc[merged['prof_band_recal'].isna(), 'essay_id'].tolist()}")

    merged = merged.drop(columns=["prof_score_pct_old"])
    return merged


def main():
    print("Combining 7 shards...")
    combined = combine_shards()
    print(f"  {len(combined)} essays combined, {combined['essay_id'].nunique()} unique IDs")

    print("Attaching quartile-recalibrated ground-truth bands...")
    combined = attach_recalibrated_bands(combined)

    combined.to_csv(OUT_PATH, index=False)
    print(f"  Saved combined dataset -> {OUT_PATH}")

    table = combined.rename(columns={
        "ai_score_pct": "score_pct",
        "ai_confidence": "confidence",
        "ai_spread": "spread",
        "prof_band_recal": "gt_band",
    })[["essay_id", "score_pct", "confidence", "spread", "gt_band", "prof_score_pct"]]

    print(f"\nBand distribution (recalibrated, n={len(table)}):")
    print(table["gt_band"].value_counts().reindex(BAND_ORDER))

    print("\n=== Correlation: AI score_pct vs professor score_pct ===")
    corr = table["score_pct"].corr(table["prof_score_pct"])
    bias = (table["score_pct"] - table["prof_score_pct"]).mean()
    print(f"  Correlation: {corr:.3f}   Mean bias (AI - Prof): {bias:+.2f}")

    print("\n=== Bias by band ===")
    for band in BAND_ORDER:
        sub = table[table["gt_band"] == band]
        band_bias = (sub["score_pct"] - sub["prof_score_pct"]).mean()
        print(f"  {band}: n={len(sub)}  mean bias={band_bias:+.2f}")

    print("\n=== Training final ordinal classifier on all 200 essays ===")
    _, result = train_ordinal_classifier(table)
    print(summarize_formula(result))

    print("\n=== 5-fold cross-validation ===")
    cv_results = cross_validate(table)
    eval_results = evaluate_predictions(cv_results)
    print(f"  n={eval_results['n']}")
    print(f"  Exact-match accuracy: {eval_results['exact_accuracy']:.2%}")
    print(f"  Adjacent-band agreement: {eval_results['adjacent_agreement']:.2%}")
    print("\n  Confusion matrix (rows=true, cols=predicted):")
    print(eval_results["confusion_matrix"])

    print("\n=== Baseline comparison ===")
    majority_band = table["gt_band"].value_counts().idxmax()
    majority_acc = (table["gt_band"] == majority_band).mean()
    print(f"  Majority-class baseline (always '{majority_band}'): {majority_acc:.2%}")
    print(f"  Trained classifier (5-fold CV): {eval_results['exact_accuracy']:.2%}")

    print("\n=== Per-band recall ===")
    confusion = eval_results["confusion_matrix"]
    for band in BAND_ORDER:
        total = confusion.loc[band].sum()
        correct = confusion.loc[band, band]
        pct = correct / total if total else float("nan")
        print(f"  {band}: {correct}/{total} = {pct:.1%}")


if __name__ == "__main__":
    main()
