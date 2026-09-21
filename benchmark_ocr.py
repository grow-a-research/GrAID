"""
benchmark_ocr.py — compare OCR engines on the submissions already collected.

READ-ONLY with respect to app data: opens the SQLite database in read-only
mode, calls the GPU host's OCR endpoints directly (never the app's own
endpoints), and writes results to a file. No stored transcription, score or
flag is modified.

Usage
-----
    python benchmark_ocr.py --url http://HOST:PORT [--engines qwen,trocr]
                            [--label "A5000 fp16"] [--out results.json]

Engines
-------
    qwen   /ocr      for essays, /ocr_id for identification (today's pipeline)
    trocr  /ocr_trocr for both (experimental handwriting model)

Reports, per engine: identification exact-match against the teacher's
accepted answers, character error rate on essays against a chosen baseline
text, and seconds per answer.
"""
from __future__ import annotations

import argparse
import io
import json
import sqlite3
import time
from pathlib import Path

import requests
from PIL import Image

from ai_grader import compute_cer
from identification_scoring import score_identification
from ocr_alignment import crop_region

DB_PATH = Path(__file__).resolve().parent / "data" / "app.db"
ESSAY_TOP_PAD_MM = -1.5


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _post(url: str, path: str, image: Image.Image, params: dict | None = None) -> dict:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    resp = requests.post(
        f"{url.rstrip('/')}/{path}",
        params=params or {},
        files={"file": ("crop.png", buf.getvalue(), "image/png")},
        timeout=900,
    )
    resp.raise_for_status()
    return resp.json()


def _aligned_page(submission_id: int) -> Image.Image | None:
    p = DB_PATH.parent / "submissions" / str(submission_id) / "aligned_p1.png"
    return Image.open(p) if p.exists() else None


def run_identification(url: str, engine: str, limit: int = 0) -> dict:
    """Exact-match accuracy over graded identification answers."""
    con = _db()
    # Questions belong to a specific exam — pair each submission only with
    # its own exam's questions, never another exam's.
    by_exam: dict[int, list] = {}
    for r in con.execute(
        "select region_json, correct_answer, case_sensitive, exam_id from exam_questions "
        "where question_type='identification' and region_json is not null "
        "and correct_answer is not null order by exam_id, order_index"
    ):
        by_exam.setdefault(r["exam_id"], []).append(
            (json.loads(r["region_json"]), r["correct_answer"], r["case_sensitive"])
        )
    specs = {
        r["id"]: json.loads(r["template_spec_json"])
        for r in con.execute("select id, template_spec_json from exams where template_spec_json is not null")
    }
    subs = [
        (r["id"], r["exam_id"]) for r in con.execute(
            "select distinct s.id, s.exam_id from submissions s "
            "join submission_answers a on a.submission_id=s.id "
            "join exam_questions q on q.id=a.question_id "
            "where q.question_type='identification' order by s.id"
        )
    ]
    if limit:
        subs = subs[:limit]
    correct = total = 0
    seconds = 0.0
    details = []
    for sub, exam_id in subs:
        page = _aligned_page(sub)
        spec = specs.get(exam_id)
        if page is None or spec is None:
            continue
        for region, answer, case_sensitive in by_exam.get(exam_id, []):
            crop = crop_region(page, region, spec, snap_to_box=True)
            t0 = time.perf_counter()
            if engine == "trocr":
                data = _post(url, "ocr_trocr", crop, {"single_line": True})
            else:
                data = _post(url, "ocr_id", crop)
            seconds += time.perf_counter() - t0
            text = data.get("text", "")
            score, _ = score_identification(answer, text, 1.0, bool(case_sensitive))
            correct += int(score > 0)
            total += 1
            details.append({"submission": sub, "expected": answer, "got": text, "correct": score > 0})
    return {
        "engine": engine, "answers": total, "correct": correct,
        "accuracy": round(correct / total, 4) if total else None,
        "seconds_per_answer": round(seconds / total, 2) if total else None,
        "details": details,
    }


def run_essays(url: str, engine: str, baseline: dict[int, str] | None) -> dict:
    """Transcribe every essay answer; CER against `baseline` when given."""
    con = _db()
    rows = list(con.execute(
        "select a.submission_id, q.region_json, q.exam_id from submission_answers a "
        "join exam_questions q on q.id=a.question_id where q.question_type='essay' "
        "and q.region_json is not null order by a.submission_id"
    ))
    specs = {
        r["id"]: json.loads(r["template_spec_json"])
        for r in con.execute("select id, template_spec_json from exams where template_spec_json is not null")
    }
    out, seconds = {}, 0.0
    cers = []
    for r in rows:
        page = _aligned_page(r["submission_id"])
        spec = specs.get(r["exam_id"])
        if page is None or spec is None:
            continue
        crop = crop_region(page, json.loads(r["region_json"]), spec, top_padding_mm=ESSAY_TOP_PAD_MM)
        t0 = time.perf_counter()
        data = _post(url, "ocr_trocr" if engine == "trocr" else "ocr", crop,
                     None if engine == "trocr" else {"include_boxed_image": False})
        seconds += time.perf_counter() - t0
        text = data.get("text", "")
        out[r["submission_id"]] = text
        if baseline and r["submission_id"] in baseline:
            cer = compute_cer(baseline[r["submission_id"]], text)
            cers.append(cer)
    return {
        "engine": engine, "essays": len(out),
        "seconds_per_essay": round(seconds / len(out), 2) if out else None,
        "mean_cer_vs_baseline": round(sum(cers) / len(cers), 4) if cers else None,
        "texts": out,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="OCR server base URL, e.g. http://1.2.3.4:40000")
    ap.add_argument("--engines", default="qwen", help="comma-separated: qwen,trocr")
    ap.add_argument("--label", default="", help="free-text label stored with the results")
    ap.add_argument("--out", default="benchmark_results.json")
    ap.add_argument("--baseline", default="", help="a previous results file; essay CER is measured against its texts")
    ap.add_argument("--limit", type=int, default=0, help="only the first N identification submissions (0 = all)")
    args = ap.parse_args()

    baseline = None
    if args.baseline:
        prev = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        for entry in prev.get("essays", []):
            if entry.get("texts"):
                baseline = {int(k): v for k, v in entry["texts"].items()}
                break

    results = {"label": args.label, "url": args.url, "identification": [], "essays": []}
    for engine in [e.strip() for e in args.engines.split(",") if e.strip()]:
        print(f"== {engine}: identification")
        ident = run_identification(args.url, engine, limit=args.limit)
        print(f"   {ident['correct']}/{ident['answers']} correct "
              f"({ident['accuracy']}), {ident['seconds_per_answer']}s per answer")
        results["identification"].append(ident)

        print(f"== {engine}: essays")
        essays = run_essays(args.url, engine, baseline)
        print(f"   {essays['essays']} essays, {essays['seconds_per_essay']}s each"
              + (f", mean CER vs baseline {essays['mean_cer_vs_baseline']}" if essays["mean_cer_vs_baseline"] is not None else ""))
        results["essays"].append(essays)

    Path(args.out).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {args.out} (no app data was modified)")


if __name__ == "__main__":
    main()
