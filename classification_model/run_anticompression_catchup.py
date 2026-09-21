"""
run_anticompression_catchup.py — grades whatever essays are still missing
across ALL 7 shards of run_anticompression_full.py (currently 68/200,
since accounts hit their daily quota at different points), using a
separate account (e.g. the thesis adviser's own, independently authorized).

Unlike the original shard scripts, this does NOT use a fixed slice — it
computes the true global gap (any essay_id not yet present in ANY of the
7 shard progress files, or in this script's own catchup file from a prior
run) and grades exactly that, so nothing already done gets re-graded and
no tokens are wasted.

Writes to its own progress file (anticompression_full_progress_catchup.csv)
so it never collides with the 7 shard files — when everything is combined
later, all 8 files (7 shards + catchup) are just concatenated.

Usage (run from repo root, GROQ_API_KEY set to the catch-up account's key):

    python -m classification_model.run_anticompression_catchup [max_this_run]

PROFESSOR_SCORES_XLSX env var overrides the default professor-scores path
(defaults to Thesis_GenED.xlsx, the current confirmed baseline).
"""

import argparse
import os
import time
from pathlib import Path

import pandas as pd

from .build_professor_batch2_workbooks import SHARED_15, select_new_185
from .classification_model import get_ai_features_for_essay
from .dress_pipeline import MAX_TOTAL_POINTS, build_dress_rubric_criteria_json, load_dress_bulk
from .few_shot_examples import ANTI_COMPRESSION_NOTE, build_few_shot_block
from .professor_ground_truth import load_professor_consensus

DEFAULT_XLSX_PATH = r"C:\Users\ASUS\Downloads\Thesis_GenED.xlsx"
XLSX_PATH = os.environ.get("PROFESSOR_SCORES_XLSX", DEFAULT_XLSX_PATH)

DEFAULT_MAX_PER_RUN = 90
N_SHARDS = 7
PROGRESS_DIR = Path(__file__).resolve().parent / "dress_data"
PROGRESS_COLUMNS = ["essay_id", "ai_score_pct", "ai_confidence", "ai_spread", "prof_score_pct", "prof_band"]
CATCHUP_PATH = PROGRESS_DIR / "anticompression_full_progress_catchup.csv"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("max_this_run", type=int, nargs="?", default=DEFAULT_MAX_PER_RUN)
    return p.parse_args()


def load_progress(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame(columns=PROGRESS_COLUMNS)


def append_progress(path: Path, row: dict) -> None:
    PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    pd.DataFrame([row], columns=PROGRESS_COLUMNS).to_csv(path, mode="a", header=is_new, index=False)


def already_done_ids() -> set[str]:
    """Union of essay_ids across all 7 shard files + this script's own catchup file."""
    done = set()
    for i in range(N_SHARDS):
        shard_path = PROGRESS_DIR / f"anticompression_full_progress_shard{i}.csv"
        if shard_path.exists():
            done |= set(pd.read_csv(shard_path)["essay_id"])
    if CATCHUP_PATH.exists():
        done |= set(pd.read_csv(CATCHUP_PATH)["essay_id"])
    return done


def main():
    args = parse_args()

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

    done_ids = already_done_ids()
    remaining = essays[~essays["essay_id"].isin(done_ids)]
    print(f"Already done across all 7 shards + catchup: {len(done_ids)}  Remaining: {len(remaining)}")

    if remaining.empty:
        print("Nothing left to grade — all 200 essays are done.")
        return

    batch = remaining.head(args.max_this_run)
    print(f"Processing {len(batch)} essays this run (cap: {args.max_this_run})...\n")

    rubric_json = build_dress_rubric_criteria_json()
    few_shot_block = build_few_shot_block() + ANTI_COMPRESSION_NOTE
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
                few_shot_examples=few_shot_block,
            )
        except Exception as e:
            print(f"[{i}/{len(batch)}] {row['essay_id']}: FAILED ({e}) — skipping, will retry next run")
            continue

        append_progress(CATCHUP_PATH, {
            "essay_id": features.essay_id,
            "ai_score_pct": features.score_pct,
            "ai_confidence": features.confidence,
            "ai_spread": features.spread,
            "prof_score_pct": row["prof_score_pct"],
            "prof_band": row["prof_band"],
        })
        elapsed = time.time() - start
        print(f"[{i}/{len(batch)}] {features.essay_id}: AI={features.score_pct:.1f}  "
              f"Prof={row['prof_score_pct']:.1f}  (elapsed {elapsed:.0f}s)")

    total_remaining = len(essays) - len(already_done_ids())
    print(f"\nDone for this run. Still remaining across the whole dataset: {total_remaining}")
    if total_remaining > 0:
        print("Re-run this same command (this account, once quota resets, or another account) to continue.")
    else:
        print("All 200 essays are now graded! Ready to combine + retrain.")


if __name__ == "__main__":
    main()
