"""
run_anticompression_full_retrain.py — combines all 8 sources of
run_anticompression_full.py / run_anticompression_catchup.py (7 shards +
1 catchup file) into the final 200-essay anti-compression dataset, attaches
the quartile-recalibrated ground-truth bands, retrains the ordinal
classifier, and reports the full-scale evaluation — same structure as
run_fewshot_full_retrain.py, for a clean before/after comparison.

Run from repo root:

    python -m classification_model.run_anticompression_full_retrain
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
OUT_PATH = DATA_DIR / "anticompression_full_combined.csv"


def combine_sources() -> pd.DataFrame:
    paths = [DATA_DIR / f"anticompression_full_progress_shard{i}.csv" for i in range(N_SHARDS)]
    paths.append(DATA_DIR / "anticompression_full_progress_catchup.csv")
    dfs = [pd.read_csv(p) for p in paths if p.exists()]
    combined = pd.concat(dfs, ignore_index=True)
    if combined["essay_id"].duplicated().any():
        dupes = combined[combined["essay_id"].duplicated(keep=False)]["essay_id"].unique()
        raise ValueError(f"Duplicate essay_ids across sources: {dupes}")
    return combined


def attach_recalibrated_bands(combined: pd.DataFrame) -> pd.DataFrame:
    """Same recalibration reasoning as run_fewshot_full_retrain.py — the
    'prof_band' column here uses the stale DREsS-native cutoffs; the
    correct quartile-recalibrated bands are pulled from
    full_200_professor_training.csv by essay_id, after verifying the
    underlying professor scores are identical."""
    old = pd.read_csv(OLD_TRAINING_PATH)[["essay_id", "prof_score_pct", "prof_band_recal"]]
    merged = combined.merge(old, on="essay_id", how="left", suffixes=("", "_old"))

    mismatch = (merged["prof_score_pct"] - merged["prof_score_pct_old"]).abs() > 0.01
    if mismatch.any():
        raise ValueError(f"Ground-truth score mismatch for: {merged.loc[mismatch, 'essay_id'].tolist()}")
    if merged["prof_band_recal"].isna().any():
        raise ValueError(f"No recalibrated band found for: {merged.loc[merged['prof_band_recal'].isna(), 'essay_id'].tolist()}")

    return merged.drop(columns=["prof_score_pct_old"])


def main():
    print("Combining 7 shards + 1 catchup file...")
    combined = combine_sources()
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
    mae = (table["score_pct"] - table["prof_score_pct"]).abs().mean()
    print(f"  Correlation: {corr:.3f}   Mean bias (AI - Prof): {bias:+.2f}   MAE: {mae:.2f}")

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
