"""
run_holistic_grading.py — resumable, shardable holistic-grading runner for
all 200 essays (15 reference + 185 new) that already have real professor
scores, to compare against the analytic/structured grading already done.

Same resumable/sharding pattern as the earlier runners — safe to stop and
re-run, splittable across multiple Groq accounts.

Usage (run from repo root, GROQ_API_KEY set):

    Solo:
        python -m classification_model.run_holistic_grading [max_this_run]

    Sharded (sizes must sum to 200):
        python -m classification_model.run_holistic_grading [max_this_run] \
            --shard-sizes 29,29,29,29,28,28,28 --shard-id 0
        ...(one invocation per shard_id, 0-indexed)...

PROFESSOR_SCORES_XLSX env var overrides the default professor-scores path.
"""

import argparse
import os
import time
from pathlib import Path

import pandas as pd

from .build_professor_batch2_workbooks import SHARED_15, select_new_185
from .dress_pipeline import MAX_TOTAL_POINTS, load_dress_bulk
from .holistic_pipeline import build_flattened_rubric_text, get_holistic_features_for_essay
from .professor_ground_truth import load_professor_consensus

DEFAULT_XLSX_PATH = r"C:\Users\ASUS\Downloads\Thesis_GenED.xlsx"
XLSX_PATH = os.environ.get("PROFESSOR_SCORES_XLSX", DEFAULT_XLSX_PATH)

DEFAULT_MAX_PER_RUN = 90
PROGRESS_DIR = Path(__file__).resolve().parent / "dress_data"
PROGRESS_COLUMNS = ["essay_id", "holistic_score_pct", "holistic_confidence", "prof_score_pct", "prof_band"]


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("max_this_run", type=int, nargs="?", default=DEFAULT_MAX_PER_RUN)
    p.add_argument("--shard-sizes", type=str, default=None)
    p.add_argument("--shard-id", type=int, default=None)
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
    return PROGRESS_DIR / f"holistic_progress{suffix}.csv"


def load_progress(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame(columns=PROGRESS_COLUMNS)


def append_progress(path: Path, row: dict) -> None:
    PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    pd.DataFrame([row], columns=PROGRESS_COLUMNS).to_csv(path, mode="a", header=is_new, index=False)


def main():
    args = parse_args()
    if args.shard_sizes is not None and args.shard_id is None:
        raise SystemExit("--shard-id is required when --shard-sizes is given")

    print("Loading all 200 essays and professor-consensus scores...")
    bulk = load_dress_bulk()
    new_185 = select_new_185()
    all_ids = SHARED_15 + new_185["essay_id"].tolist()
    essays = bulk[bulk["essay_id"].isin(all_ids)][["essay_id", "question_prompt", "essay_text"]]

    consensus = load_professor_consensus(XLSX_PATH)
    essays = essays.merge(consensus, on="essay_id", how="left")
    if essays["prof_score_pct"].isna().any():
        missing = essays[essays["prof_score_pct"].isna()]["essay_id"].tolist()
        raise ValueError(f"No professor score found for: {missing}")
    essays = essays.sort_values("essay_id").reset_index(drop=True)

    if args.shard_sizes is not None:
        shard_sizes = [int(x) for x in args.shard_sizes.split(",")]
        essays = get_shard(essays, shard_sizes, args.shard_id)
        print(f"Shard {args.shard_id} of sizes {shard_sizes}: {len(essays)} essays assigned to this run")
    else:
        print(f"Solo mode: all {len(essays)} essays assigned to this run")

    progress_path = progress_path_for(args.shard_id)
    progress_df = load_progress(progress_path)
    done_ids = set(progress_df["essay_id"])
    remaining = essays[~essays["essay_id"].isin(done_ids)]
    print(f"Already done: {len(done_ids)}  Remaining: {len(remaining)}")

    if remaining.empty:
        print("This shard is fully processed.")
        return

    batch = remaining.head(args.max_this_run)
    print(f"Processing {len(batch)} essays this run (cap: {args.max_this_run})...\n")

    rubric_text = build_flattened_rubric_text()
    start = time.time()
    for i, (_, row) in enumerate(batch.iterrows(), start=1):
        try:
            features = get_holistic_features_for_essay(
                essay_id=row["essay_id"],
                question_prompt=row["question_prompt"],
                rubric_text=rubric_text,
                max_points=MAX_TOTAL_POINTS,
                essay_text=row["essay_text"],
            )
        except Exception as e:
            print(f"[{i}/{len(batch)}] {row['essay_id']}: FAILED ({e}) — skipping, will retry next run")
            continue

        append_progress(progress_path, {
            "essay_id": features.essay_id,
            "holistic_score_pct": features.score_pct,
            "holistic_confidence": features.confidence,
            "prof_score_pct": row["prof_score_pct"],
            "prof_band": row["prof_band"],
        })
        elapsed = time.time() - start
        print(f"[{i}/{len(batch)}] {features.essay_id}: Holistic={features.score_pct:.1f}  "
              f"Prof={row['prof_score_pct']:.1f}  (elapsed {elapsed:.0f}s)")

    total_done = len(load_progress(progress_path))
    shard_total = len(essays)
    print(f"\nDone for this run. Progress: {total_done}/{shard_total}")
    if total_done < shard_total:
        print("Re-run this same command to continue.")
    else:
        print(f"Complete! ({progress_path.name})")


if __name__ == "__main__":
    main()
