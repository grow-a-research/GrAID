"""
export_identification.py — build the evaluation workbook's inputs from the
graded submissions already in the database.

READ-ONLY with respect to app data: opens SQLite in read-only mode and writes
only into this script's own output directory. No stored transcription, score,
flag or status is modified, and nothing is re-graded through the app. The
evaluation stands beside the system rather than mutating it.

Commands
--------
    workbook   Columns A-K of the Data sheet, as a CSV to paste in.
    crops      One PNG per answer — the same crop the OCR actually saw.
    sheets     The blind collection sheets: two transcription sheets and one
               professor sheet.
    metrics    After the transcriptions come back: character and word edit
               distances for columns J and K, which Excel cannot compute.

Typical order
-------------
    python eval/export_identification.py workbook
    python eval/export_identification.py crops
    python eval/export_identification.py sheets
    ... humans fill in the sheets ...
    python eval/export_identification.py metrics --filled eval/out/filled.csv

Why column D is left blank
--------------------------
The accepted-variants list is a teaching decision the professor makes from the
question itself, and it must be frozen before any result is seen. Exporting the
current answer key into column D would quietly turn "what the professor decided"
into "whatever was in the database that day". Fill D by hand from the frozen
list, then never change it.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

DEFAULT_DB   = REPO / "data" / "app.db"
DEFAULT_EXAM = 15          # "ID-1"
OUT_DIR      = REPO / "eval" / "out"
SHUFFLE_SEED = 20260921    # recorded in the manifest so the order is reproducible

# Punctuation the workbook's M-Q formulas delete before comparing. Mirrored here
# so the edit distances in columns J and K are measured on the same text the
# workbook's own exact-transcription columns compare. NOTE: this is deliberately
# NOT what the live scorer does — identification_scoring._normalize() only trims
# whitespace and casefolds, leaving punctuation intact. Pass --raw-cer to measure
# standard CER/WER on untouched text instead.
_WORKBOOK_STRIPPED = ".,;:!?\"'’“”"


# ── shared helpers ──────────────────────────────────────────────────────────

def _db(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def item_id(submission_id: int, order_index: int) -> str:
    """Stable, sortable, traceable back to the exact answer row."""
    return f"S{submission_id}-Q{order_index:02d}"


def _answers(con: sqlite3.Connection, exam_id: int) -> list[sqlite3.Row]:
    return list(con.execute(
        "select a.id as answer_id, a.submission_id, a.page_number, a.ocr_text, "
        "       a.ai_score, a.status, "
        "       q.id as question_id, q.order_index, q.prompt, q.correct_answer, "
        "       q.case_sensitive, q.region_json, e.template_spec_json "
        "from submission_answers a "
        "join exam_questions q on q.id = a.question_id "
        "join exams e on e.id = q.exam_id "
        "where q.exam_id = ? and q.question_type = 'identification' "
        "order by a.submission_id, q.order_index",
        (exam_id,),
    ))


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so Excel on Windows opens the accents correctly on a double-click.
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  wrote {path.relative_to(REPO)}  ({len(rows)} rows)")


def _manifest(db: Path, exam_id: int, extra: dict) -> None:
    """Provenance record — which database, which build, when, what settings."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True
        ).stdout.strip() or "unknown"
        dirty = bool(subprocess.run(
            ["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True
        ).stdout.strip())
    except Exception:
        commit, dirty = "unknown", None

    path = OUT_DIR / "manifest.json"
    existing = json.loads(path.read_text()) if path.exists() else {}
    existing.update({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": str(db),
        "exam_id": exam_id,
        "git_commit": commit,
        "working_tree_dirty": dirty,
        **extra,
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=2))
    print(f"  wrote {path.relative_to(REPO)}")


def _check_db(db: Path) -> None:
    if "frozen" not in db.name:
        print(
            f"NOTE: reading {db.name}, not a frozen copy. Phase 1.3 of the protocol\n"
            f"      says to snapshot the database before exporting, so the export can\n"
            f"      be reproduced later. Pass --db data/app_frozen_<date>.db once the\n"
            f"      snapshot exists.\n"
        )


# ── workbook ────────────────────────────────────────────────────────────────

def cmd_workbook(args) -> None:
    """Columns A-K of the Data sheet. D, E, H and L are left for humans."""
    con = _db(args.db)
    rows_in = _answers(con, args.exam)
    out: list[list] = []
    empty_ocr: list[str] = []
    routed = 0

    for r in rows_in:
        raw = (r["ocr_text"] or "").strip()
        if not raw:
            empty_ocr.append(item_id(r["submission_id"], r["order_index"]))
        # Column I counts MANDATORY review only. Every wrong answer also picks up
        # an automatic identification_no_match flag, so counting flag rows here
        # would push Analysis E to ~100% and measure nothing.
        review = 1 if r["status"] == "needs_review" else 0
        routed += review
        out.append([
            item_id(r["submission_id"], r["order_index"]),  # A  Item ID
            args.professor,                                 # B  Professor
            r["correct_answer"] or "",                      # C  Answer key
            "",                                             # D  Accepted variants — frozen list, by hand
            "",                                             # E  Reference transcription — transcribers
            raw,                                            # F  GrAid raw transcription
            raw,                                            # G  GrAid corrected — identical: no correction step
            "",                                             # H  Professor judgment
            review,                                         # I  Routed to review (needs_review)
            "",                                             # J  Char errors — the metrics command
            "",                                             # K  Word errors — the metrics command
        ])

    _write_csv(
        OUT_DIR / "workbook_rows.csv",
        ["item_id", "professor", "answer_key", "accepted_variants",
         "reference_transcription", "graid_raw", "graid_corrected",
         "professor_judgment", "routed_to_review", "char_errors", "word_errors"],
        out,
    )
    _manifest(args.db, args.exam, {
        "workbook_rows": len(out),
        "routed_to_review": routed,
        "empty_ocr_items": empty_ocr,
    })

    print(f"\n  {len(out)} answers, {routed} routed to review, {len(empty_ocr)} with empty OCR.")
    if empty_ocr:
        print(f"  Empty OCR: {', '.join(empty_ocr)}")
        print("  These were never scored (the grading loop skips answers with no text,\n"
              "  so ai_score is NULL, not 0). The workbook will treat them as zero\n"
              "  credit because columns F and G are blank. State that in Chapter 3.")
    print("\n  Paste rows 2+ into the Data sheet starting at cell A5.")
    print("  Column G is a copy of F: identification never runs the LLM correction\n"
          "  step, so 'change from the correction step' will read 0.0 by design.")
    print("  Column D stays blank until the professor's frozen variants list arrives.")


# ── crops ───────────────────────────────────────────────────────────────────

def cmd_crops(args) -> None:
    """One PNG per answer, cropped exactly as the OCR pipeline crops it."""
    from PIL import Image
    from ocr_alignment import crop_region

    con = _db(args.db)
    crops_dir = OUT_DIR / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    missing: list[str] = []
    pages: dict[tuple[int, int], object] = {}

    for r in _answers(con, args.exam):
        iid = item_id(r["submission_id"], r["order_index"])
        if not r["region_json"] or not r["template_spec_json"]:
            missing.append(f"{iid} (no region/template)")
            continue

        key = (r["submission_id"], r["page_number"])
        if key not in pages:
            p = (REPO / "data" / "submissions" / str(r["submission_id"])
                 / f"aligned_p{r['page_number']}.png")
            pages[key] = Image.open(p) if p.exists() else None
        page = pages[key]
        if page is None:
            missing.append(f"{iid} (no aligned page)")
            continue

        # snap_to_box=True and the default 0.5mm top padding match the live
        # identification path (_TOP_PAD_MM has no entry for identification).
        crop = crop_region(page, json.loads(r["region_json"]),
                           json.loads(r["template_spec_json"]), snap_to_box=True)
        crop.save(crops_dir / f"{iid}.png")
        written += 1

    print(f"\n  {written} crops -> {crops_dir.relative_to(REPO)}")
    if missing:
        print(f"  {len(missing)} could not be cropped — report these as exclusions:")
        for m in missing:
            print(f"    {m}")
    _manifest(args.db, args.exam, {"crops_written": written, "crops_missing": missing})


# ── blind collection sheets ─────────────────────────────────────────────────

def cmd_sheets(args) -> None:
    """
    The sheets humans fill in. What each one deliberately omits matters:

      transcription sheet — no answer key, no GrAid output. The transcriber
                            records what is written, nothing more.
      professor sheet     — no GrAid output, no reference transcription, and
                            rows shuffled. Judging in paper order drifts into
                            grading papers instead of judging items; seeing
                            GrAid's score lets GrAid influence its own judge.
    """
    con = _db(args.db)
    rows_in = _answers(con, args.exam)

    trans = [[item_id(r["submission_id"], r["order_index"]),
              f"crops/{item_id(r['submission_id'], r['order_index'])}.png", ""]
             for r in rows_in]
    for who in ("A", "B"):
        _write_csv(OUT_DIR / f"transcription_sheet_{who}.csv",
                   ["item_id", "crop_image", "transcription"], trans)

    prof = [[item_id(r["submission_id"], r["order_index"]),
             f"crops/{item_id(r['submission_id'], r['order_index'])}.png",
             r["prompt"] or "",
             r["correct_answer"] or "",
             ""]
            for r in rows_in]
    random.Random(SHUFFLE_SEED).shuffle(prof)
    _write_csv(OUT_DIR / "professor_sheet.csv",
               ["item_id", "crop_image", "question_prompt",
                "accepted_answers", "judgment_1_correct_0_incorrect"], prof)

    _manifest(args.db, args.exam, {"shuffle_seed": SHUFFLE_SEED, "sheet_rows": len(rows_in)})
    print("\n  The professor sheet's 'accepted_answers' column holds the CURRENT key.")
    print("  Regenerate this sheet once the frozen variants list is decided, or the\n"
          "  professor will be judging against a list that later changes.")


# ── metrics ─────────────────────────────────────────────────────────────────

def _normalize(text: str, raw: bool) -> str:
    text = (text or "").strip()
    if raw:
        return " ".join(text.split())
    for ch in _WORKBOOK_STRIPPED:
        text = text.replace(ch, "")
    return " ".join(text.lower().split())


def cmd_metrics(args) -> None:
    """
    Columns J and K: edit distances Excel cannot compute.

    Reuses ai_grader._edit_distance so these counts come from the same
    implementation the rest of the project's CER/WER uses.
    """
    from ai_grader import _edit_distance

    with args.filled.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    def col(row: dict, *names: str) -> str:
        for n in names:
            for k in row:
                if k and k.strip().lower() == n:
                    return (row[k] or "").strip()
        return ""

    out: list[list] = []
    tot_ce = tot_we = tot_rc = tot_rw = exact = scored = 0

    for row in rows:
        iid = col(row, "item_id", "a", "item id")
        ref = col(row, "reference_transcription", "reference", "e")
        hyp = col(row, "graid_raw", "raw", "f")
        if not iid:
            continue
        if not ref:
            out.append([iid, "", ""])      # not transcribed yet — leave blank
            continue

        r_n, h_n = _normalize(ref, args.raw_cer), _normalize(hyp, args.raw_cer)
        ce = _edit_distance(list(r_n), list(h_n))
        we = _edit_distance(r_n.split(), h_n.split())
        out.append([iid, ce, we])

        scored += 1
        tot_ce += ce
        tot_we += we
        tot_rc += len(r_n)
        tot_rw += len(r_n.split())
        exact += int(r_n == h_n)

    _write_csv(OUT_DIR / "metrics_JK.csv", ["item_id", "char_errors", "word_errors"], out)

    mode = "raw text" if args.raw_cer else "workbook normalization (lowercased, punctuation stripped)"
    print(f"\n  Measured on {mode}.")
    print(f"  Answers with a reference transcription: {scored} of {len(rows)}")
    if scored:
        print(f"  Pooled CER  {tot_ce}/{tot_rc} = {tot_ce / tot_rc:.4f}" if tot_rc else "  Pooled CER  n/a")
        print(f"  Pooled WER  {tot_we}/{tot_rw} = {tot_we / tot_rw:.4f}" if tot_rw else "  Pooled WER  n/a")
        print(f"  Exact-transcription rate  {exact}/{scored} = {exact / scored:.4f}")
    print("\n  Paste char_errors and word_errors into columns J and K.")
    print("  The three figures above should match the Summary sheet once pasted —\n"
          "  if they don't, the workbook's ranges or formulas are off.")


# ── entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="database to read (read-only)")
    ap.add_argument("--exam", type=int, default=DEFAULT_EXAM, help="exam id (default 15 = ID-1)")
    sub = ap.add_subparsers(dest="command", required=True)

    w = sub.add_parser("workbook", help="columns A-K as a paste-ready CSV")
    w.add_argument("--professor", default="P1", help="value for column B")
    w.set_defaults(func=cmd_workbook)

    sub.add_parser("crops", help="one PNG per answer").set_defaults(func=cmd_crops)
    sub.add_parser("sheets", help="blind transcription and professor sheets").set_defaults(func=cmd_sheets)

    m = sub.add_parser("metrics", help="columns J and K from the filled sheet")
    m.add_argument("--filled", type=Path, required=True,
                   help="CSV with item_id, reference_transcription and graid_raw columns "
                        "— save the workbook's Data sheet as CSV once column E is filled")
    m.add_argument("--raw-cer", action="store_true",
                   help="measure on untouched text instead of the workbook's normalization")
    m.set_defaults(func=cmd_metrics)

    args = ap.parse_args()
    if not args.db.exists():
        sys.exit(f"database not found: {args.db}")
    if getattr(args, "filled", None) is not None and not args.filled.exists():
        # Running metrics before the humans have finished is the normal way to
        # hit this, so say what is missing rather than raising FileNotFoundError.
        sys.exit(
            f"no such file: {args.filled}\n\n"
            "'metrics' is the LAST step. It needs the reference transcriptions,\n"
            "so it only works once your transcribers have finished and their work\n"
            "is in the workbook. To produce the file it wants:\n"
            "  1. fill Data column E (reference transcription) for every answer\n"
            "  2. File > Save As > CSV UTF-8, saving the Data sheet\n"
            "  3. rerun with --filled pointing at that CSV\n\n"
            "Until then, the exports you already have are all you need:\n"
            "  eval/out/workbook_rows.csv, eval/out/crops/, the three sheets."
        )
    _check_db(args.db)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    args.func(args)


if __name__ == "__main__":
    main()
