"""
build_professor_workbook.py — the first-pass judgment sheet.

A CSV of filenames is useless to someone marking 250 answers: they would have
to open 250 PNGs by hand. This builds one Excel file with each student's
handwriting embedded directly in its row, so judging is scroll, look, pick
from a drop-down. The layout itself lives in judgment_sheet.py, shared with
the blind re-check.

What the professor deliberately does NOT see
--------------------------------------------
GrAid's transcription and GrAid's score are both absent. The professor's
judgment is the yardstick the system is measured against, so if they can see
what GrAid decided, GrAid ends up influencing its own judge.

Row order is shuffled with a fixed seed. In paper order a marker drifts into
grading whole papers instead of judging individual answers.

Usage
-----
    ./venv/Scripts/python.exe eval/build_professor_workbook.py

Needs the venv: Pillow for the image resizing.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from export_identification import (  # noqa: E402
    DEFAULT_DB, DEFAULT_EXAM, OUT_DIR, SHUFFLE_SEED, _answers, _db, item_id,
)
from judgment_sheet import build_workbook, guard_overwrite  # noqa: E402

INTRO = [
    ("Thank you for doing this. It should take about an hour.", False),
    ("", False),
    ("What you are doing", True),
    ("Go to the 'Judgments' sheet. Each row shows one student's handwritten answer as a photo, "
     "with the question it answers. For each one, decide whether the student got it right.", False),
    ("", False),
    ("Why you cannot see the system's answers", True),
    ("Nothing here shows what GrAid read or what score it gave. Your judgment is the standard we "
     "measure the system against, so it has to be formed independently. The rows are also "
     "shuffled, so answers from one student are scattered — that is deliberate.", False),
]


def build(args) -> None:
    guard_overwrite(OUT_DIR / args.out, args.force)
    con = _db(args.db)
    rows = _answers(con, args.exam)
    random.Random(SHUFFLE_SEED).shuffle(rows)

    items = [{"iid": item_id(r["submission_id"], r["order_index"]),
              "prompt": r["prompt"] or "",
              "accepted": r["correct_answer"] or ""} for r in rows]

    dest = OUT_DIR / args.out
    missing = build_workbook(items, OUT_DIR / "crops", dest,
                             "Judging GrAid's identification answers", INTRO)

    print(f"  wrote {dest.relative_to(REPO)}  "
          f"({len(items)} answers, {dest.stat().st_size / 1024 / 1024:.1f} MB)")
    if missing:
        print(f"  {len(missing)} crops were missing: {', '.join(missing)}")
        print("  Run 'export_identification.py crops' first.")

    manifest = OUT_DIR / "manifest.json"
    if manifest.exists():
        data = json.loads(manifest.read_text())
        data["professor_workbook"] = {
            "file": args.out, "answers": len(items),
            "shuffle_seed": SHUFFLE_SEED, "missing_crops": missing,
        }
        manifest.write_text(json.dumps(data, indent=2))

    print("\n  The 'Accepted answers' column holds the CURRENT key. Rebuild this file")
    print("  after the professor's frozen variants list is agreed, or they will be")
    print("  judging against a list that changes afterwards.")
    print("\n  When it comes back: match column B (Item ID) into the evaluation")
    print("  workbook's Data column H, since the rows here are shuffled.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--exam", type=int, default=DEFAULT_EXAM)
    ap.add_argument("--force", action="store_true",
                    help="overwrite the output even if it already holds judgments")
    ap.add_argument("--out", default="Professor_Judgment_ID-1.xlsx")
    args = ap.parse_args()
    if not args.db.exists():
        sys.exit(f"database not found: {args.db}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    build(args)


if __name__ == "__main__":
    main()
