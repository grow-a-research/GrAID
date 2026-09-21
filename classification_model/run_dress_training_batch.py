"""
run_dress_training_batch.py — resumable feature-extraction runner for the
500-essay stratified DREsS_New training sample.

Groq's free-tier daily token limit for openai/gpt-oss-120b (~200K TPD,
measured at ~1,967 tokens/essay from the 15-essay smoke test => roughly
~100 essays/day) means the 500-essay sample has to be processed across
several days/sessions on a free account. This script is safe to stop and
re-run: every completed essay is appended to a local progress file
immediately, and each run skips essays already done.

Supports sharding across two separate Groq accounts (e.g. a teammate's
own, independently-authorized paid account) so both can work through
disjoint, non-overlapping slices of the SAME 500-essay sample in
parallel. Sharding is a contiguous split of the deterministic sample (not
random per-run), so both sides always agree on which essay belongs to
which shard without needing to coordinate live.

The progress file(s) live under classification_model/dress_data/, which
is gitignored — they contain DREsS ground-truth values (not the essay
text itself), see .gitignore for why.

Usage (run from repo root, in a shell where GROQ_API_KEY is set):

    Solo (no sharding):
        python -m classification_model.run_dress_training_batch [max_this_run]

    Sharded across two accounts — one invocation per account/machine,
    sizes must sum to 500, shard_id is 0-indexed:
        python -m classification_model.run_dress_training_batch [max_this_run] \
            --shard-sizes 150,350 --shard-id 0

        python -m classification_model.run_dress_training_batch [max_this_run] \
            --shard-sizes 150,350 --shard-id 1

max_this_run defaults to 90 (comfortably under the ~100/day free-tier
estimate). On a paid account with a higher daily limit, pass a larger
number to finish that shard in fewer runs.
"""

import argparse
import time
from pathlib import Path

import pandas as pd

from .classification_model import get_ai_features_for_essay
from .dress_pipeline import (
    MAX_TOTAL_POINTS,
    build_dress_rubric_criteria_json,
    load_dress_bulk,
    select_stratified_sample,
)

SAMPLE_SIZE = 500
SAMPLE_SEED = 42
DEFAULT_MAX_PER_RUN = 90

PROGRESS_DIR = Path(__file__).resolve().parent / "dress_data"
PROGRESS_COLUMNS = ["essay_id", "score_pct", "confidence", "spread", "gt_score_pct", "gt_band"]


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("max_this_run", type=int, nargs="?", default=DEFAULT_MAX_PER_RUN)
    p.add_argument("--shard-sizes", type=str, default=None,
                    help="Comma-separated contiguous split sizes, must sum to 500, e.g. 150,350")
    p.add_argument("--shard-id", type=int, default=None,
                    help="0-indexed shard this invocation handles (required if --shard-sizes is given)")
    return p.parse_args()


def get_shard(sample_df: pd.DataFrame, shard_sizes: list[int], shard_id: int) -> pd.DataFrame:
    if sum(shard_sizes) != len(sample_df):
        raise ValueError(f"--shard-sizes sums to {sum(shard_sizes)}, expected {len(sample_df)}")
    if not (0 <= shard_id < len(shard_sizes)):
        raise ValueError(f"--shard-id must be 0..{len(shard_sizes) - 1}")
    start = sum(shard_sizes[:shard_id])
    end = start + shard_sizes[shard_id]
    return sample_df.iloc[start:end]


def progress_path_for(shard_id: int | None) -> Path:
    suffix = f"_shard{shard_id}" if shard_id is not None else ""
    return PROGRESS_DIR / f"dress_training_progress{suffix}.csv"


def load_progress(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame(columns=PROGRESS_COLUMNS)


def append_progress(path: Path, row: dict) -> None:
    PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    pd.DataFrame([row], columns=PROGRESS_COLUMNS).to_csv(
        path, mode="a", header=is_new, index=False,
    )


def main():
    args = parse_args()

    if args.shard_sizes is not None and args.shard_id is None:
        raise SystemExit("--shard-id is required when --shard-sizes is given")

    print("Loading DREsS_New bulk data...")
    bulk_df = load_dress_bulk()
    sample_df = select_stratified_sample(bulk_df, SAMPLE_SIZE, seed=SAMPLE_SEED)
    print(f"Full target sample: {SAMPLE_SIZE} essays (stratified, seed={SAMPLE_SEED})")

    if args.shard_sizes is not None:
        shard_sizes = [int(x) for x in args.shard_sizes.split(",")]
        sample_df = get_shard(sample_df, shard_sizes, args.shard_id)
        print(f"Shard {args.shard_id} of sizes {shard_sizes}: {len(sample_df)} essays assigned to this run")

    progress_path = progress_path_for(args.shard_id)
    progress_df = load_progress(progress_path)
    done_ids = set(progress_df["essay_id"])
    remaining = sample_df[~sample_df["essay_id"].isin(done_ids)]

    print(f"Already done (from previous runs, {progress_path.name}): {len(done_ids)}")
    print(f"Remaining in this shard: {len(remaining)}")

    if remaining.empty:
        print("This shard is fully processed. Nothing left to do here.")
        return

    batch = remaining.head(args.max_this_run)
    print(f"Processing {len(batch)} essays this run (cap: {args.max_this_run})...\n")

    rubric_json = build_dress_rubric_criteria_json()
    start = time.time()
    for i, (_, row) in enumerate(batch.iterrows(), start=1):
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
            print(f"[{i}/{len(batch)}] {row['essay_id']}: FAILED ({e}) — skipping, will retry next run")
            continue

        append_progress(progress_path, {
            "essay_id": features.essay_id,
            "score_pct": features.score_pct,
            "confidence": features.confidence,
            "spread": features.spread,
            "gt_score_pct": row["gt_score_pct"],
            "gt_band": row["gt_band"],
        })
        elapsed = time.time() - start
        print(f"[{i}/{len(batch)}] {features.essay_id}: score_pct={features.score_pct:.1f} "
              f"confidence={features.confidence:.3f} spread={features.spread:.1f}  "
              f"(elapsed {elapsed:.0f}s)")

    total_done = len(load_progress(progress_path))
    shard_total = len(sample_df)
    print(f"\nDone for this run. This shard's progress: {total_done}/{shard_total}")
    if total_done < shard_total:
        print("Re-run this same command (same shard args) to continue.")
    else:
        print(f"This shard is complete! ({progress_path.name})")


if __name__ == "__main__":
    main()
