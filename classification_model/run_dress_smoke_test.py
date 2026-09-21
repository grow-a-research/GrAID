"""
run_dress_smoke_test.py — one-off smoke test: run a small batch of
DREsS_New essays through the real AI grader (live Groq API calls) and
print the resulting score_pct/confidence/spread per essay.

Purpose: (1) confirm the DREsS rubric_criteria_json format works end to
end with ai_grader.grade_essay(), (2) get a real per-essay timing number
to extrapolate to the full 1,911-essay batch, and (3) check with real
data whether `confidence` actually varies across essays or is stuck at a
constant — flagged as a concern before committing to the full run.

Run from the repo root, in a shell where GROQ_API_KEY is already set:

    python -m classification_model.run_dress_smoke_test [N]

N defaults to 15.
"""

import sys
import time

from .dress_pipeline import assemble_training_table_from_dress, get_ai_features_for_dress, load_dress_bulk


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 15

    print("Loading DREsS_New bulk data...")
    df = load_dress_bulk()
    print(f"Loaded {len(df)} eligible essays (>=150 words). Running the first {n} through the AI grader...\n")

    start = time.time()
    features = get_ai_features_for_dress(df, limit=n)
    elapsed = time.time() - start

    print(f"{'essay_id':<12} {'score_pct':>10} {'confidence':>11} {'spread':>8}")
    for f in features:
        print(f"{f.essay_id:<12} {f.score_pct:>10.1f} {f.confidence:>11.3f} {f.spread:>8.1f}")

    confidences = [f.confidence for f in features]
    print(f"\nTotal time: {elapsed:.1f}s for {n} essays ({elapsed / n:.1f}s/essay average)")
    print(f"Confidence range: {min(confidences):.3f} - {max(confidences):.3f}")
    if max(confidences) - min(confidences) < 0.01:
        print(
            "WARNING: confidence is essentially constant across every essay in this batch — "
            "this is exactly the failure mode to check for. Either the model isn't varying it, "
            "or something upstream is defaulting/overwriting it."
        )
    else:
        print("Confidence does vary across essays in this batch (not a flat constant).")

    table = assemble_training_table_from_dress(df.head(n), features)
    print("\nWith ground truth:")
    print(table[["essay_id", "score_pct", "confidence", "spread", "gt_score_pct", "gt_band"]].to_string(index=False))


if __name__ == "__main__":
    main()
