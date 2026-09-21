"""
build_coordinator_report.py — compiles all analysis done on the professor
vs. AI grading comparison into one Excel workbook, for the user to bring
to the GenEd coordinator. Covers: the classifier's final performance
numbers, essay-by-essay AI vs professor score comparison, the professor
data-integrity checks, and the raw per-professor per-criterion scores for
full transparency.

Run from repo root:

    python -m classification_model.build_coordinator_report
"""

from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .build_professor_batch2_workbooks import SHARED_15
from .dress_pipeline import load_dress_bulk

FIRST15_FILL = PatternFill(start_color="C6E0B4", end_color="C6E0B4", fill_type="solid")

DATA_DIR = Path(__file__).resolve().parent / "dress_data"
OUT_PATH = DATA_DIR / "GrAId_Classifier_Analysis_for_Coordinator_v3.xlsx"

HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
HEADER_FONT = Font(bold=True, color="FFFFFF")
FLAG_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")


def style_header(ws, row=1):
    for cell in ws[row]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def autosize(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def main():
    merged = pd.read_pickle(DATA_DIR / "_merged_analysis.pkl")

    wb = Workbook()

    # ── Sheet 1: Summary ────────────────────────────────────────────────
    ws = wb.active
    ws.title = "Summary"
    rows = [
        ("GrAId Essay Classifier — Analysis Summary", ""),
        ("Dataset", "200 essays (DREsS_New), scored by AI and by 5 GenEd professors each"),
        ("Ground truth source", "Thesis_GenED.xlsx — 5-professor consensus per criterion, averaged"),
        ("", ""),
        ("CLASSIFIER PERFORMANCE (final, reported result)", ""),
        ("Exact-match accuracy (5-fold cross-validation)", "47.50%"),
        ("Majority-class baseline (always guess most common band)", "27.00%"),
        ("Adjacent-band agreement", "80.00%"),
        ("AI score vs. professor score correlation", "0.535"),
        ("", ""),
        ("BIAS BY PERFORMANCE BAND (AI score minus professor score)", ""),
        ("Poor essays", "+12.08 (AI scores these too generously)"),
        ("Fair essays", "+6.06"),
        ("Good essays", "+1.62"),
        ("Excellent essays", "-5.90 (AI scores these too conservatively)"),
        ("", ""),
        ("PROFESSOR DATA INTEGRITY CHECK (on Thesis_GenED.xlsx)", ""),
        ("Non-integer or out-of-range score cells found", "0 out of 3,000"),
        ("Essay-criterion groups where all 5 professors gave an identical score", "Content 4.5%, Organization 10.0%, Language 4.5%"),
        ("Average spread across the 5 professors per essay", "0.55-0.61 (realistic, not artificially tight)"),
        ("Conclusion", "No statistical signs of fabricated/copied scores in this file"),
        ("", ""),
        ("INTER-RATER (PROFESSOR vs. PROFESSOR) AGREEMENT", ""),
        ("Criterion with LEAST agreement among the 5 professors", "Language (avg spread 0.611)"),
        ("Criterion with MOST agreement among the 5 professors", "Organization (avg spread 0.557)"),
        ("Correlation: professor disagreement vs. AI-professor gap", "0.011 (essentially none)"),
        ("Interpretation", "The AI's disagreement with professors is NOT concentrated on essays "
                            "professors themselves find ambiguous. It is a separate, systematic "
                            "pattern (score compression by band, see above)."),
        ("", ""),
        ("OPEN ITEMS / NOT YET DONE", ""),
        ("Test-retest check (same professor, same essay, regraded blind)", "Not yet performed"),
        ("Blind independent re-grade by a different professor", "Not yet performed"),
    ]
    for r, (label, value) in enumerate(rows, start=1):
        ws.cell(row=r, column=1, value=label).font = Font(bold=label.isupper() or r == 1)
        ws.cell(row=r, column=2, value=value)
        ws.cell(row=r, column=1).alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(row=r, column=2).alignment = Alignment(wrap_text=True, vertical="top")
    autosize(ws, [50, 70])

    # ── Sheet 2: Essay-by-essay comparison, sorted by biggest gap ───────
    bulk = load_dress_bulk().set_index("essay_id")

    ws2 = wb.create_sheet("Essay Comparison")
    comp = merged[["essay_id", "gt_band", "prof_score_pct", "score_pct", "ai_gap", "prof_disagreement_stdev"]].copy()
    comp = comp.rename(columns={
        "score_pct": "ai_score_pct",
        "prof_disagreement_stdev": "prof_interrater_stdev",
    })
    comp["question_prompt"] = comp["essay_id"].map(lambda eid: bulk.loc[eid, "question_prompt"] if eid in bulk.index else "")
    comp["essay_text"] = comp["essay_id"].map(lambda eid: bulk.loc[eid, "essay_text"] if eid in bulk.index else "")
    comp["is_shared15"] = comp["essay_id"].isin(SHARED_15)
    # top-20-by-gap flag computed BEFORE resorting, so it stays tied to the
    # essay itself rather than to a row position that changes once the
    # shared-15 essays get pinned to the top
    comp["top20_gap"] = comp["ai_gap"].rank(ascending=False, method="first") <= 20
    # shared-15 essays first (in their original graded order), then
    # everything else sorted by biggest AI-vs-professor gap
    comp = comp.sort_values(["is_shared15", "ai_gap"], ascending=[False, False]).reset_index(drop=True)

    headers = ["Essay ID", "First 15 (shared multi-rater batch)", "Band (recalibrated)", "Professor Score %",
               "AI Score %", "AI - Professor Gap", "Professor Inter-rater StDev", "Question Prompt", "Essay Text"]
    ws2.append(headers)
    style_header(ws2)
    for _, row in comp.iterrows():
        ws2.append([
            row["essay_id"], "Yes" if row["is_shared15"] else "",
            row["gt_band"],
            round(row["prof_score_pct"], 2), round(row["ai_score_pct"], 2),
            round(row["ai_score_pct"] - row["prof_score_pct"], 2),
            round(row["prof_interrater_stdev"], 3),
            row["question_prompt"],
            row["essay_text"],
        ])
    # highlight: the pinned first-15 batch in green, the top-20-biggest-gap
    # essays (wherever they land) in red — a row can be both
    for i, (_, row) in enumerate(comp.iterrows(), start=2):
        fill = FIRST15_FILL if row["is_shared15"] else (FLAG_FILL if row["top20_gap"] else None)
        if fill:
            for c in range(1, 10):
                ws2.cell(row=i, column=c).fill = fill
    for r in range(2, ws2.max_row + 1):
        ws2.cell(row=r, column=8).alignment = Alignment(wrap_text=True, vertical="top")
        ws2.cell(row=r, column=9).alignment = Alignment(wrap_text=True, vertical="top")
        ws2.row_dimensions[r].height = 60
    autosize(ws2, [14, 14, 20, 16, 12, 16, 22, 40, 90])
    ws2.freeze_panes = "A2"

    # ── Sheet 3: Professor data-integrity detail ────────────────────────
    ws3 = wb.create_sheet("Data Integrity Detail")
    import numpy as np
    content_arr = np.array(merged["content"].tolist(), dtype=float)
    org_arr = np.array(merged["org"].tolist(), dtype=float)
    lang_arr = np.array(merged["lang"].tolist(), dtype=float)

    ws3.append(["Criterion", "Avg inter-rater StDev", "Rows all-5-identical", "% all-5-identical",
                "Prof 1 mean", "Prof 2 mean", "Prof 3 mean", "Prof 4 mean", "Prof 5 mean"])
    style_header(ws3)
    for name, arr in [("Content", content_arr), ("Organization", org_arr), ("Language", lang_arr)]:
        stdevs = arr.std(axis=1)
        identical = int((stdevs == 0).sum())
        means = arr.mean(axis=0)
        ws3.append([name, round(stdevs.mean(), 3), identical, f"{identical/len(arr):.1%}"] +
                   [round(m, 2) for m in means])
    autosize(ws3, [16, 20, 18, 16, 12, 12, 12, 12, 12])

    # ── Sheet 4: Raw per-professor scores (full transparency) ──────────
    ws4 = wb.create_sheet("Raw Professor Scores")
    headers4 = ["Essay ID"]
    for crit in ["Content", "Organization", "Language"]:
        for p in range(1, 6):
            headers4.append(f"{crit} - Prof {p}")
    ws4.append(headers4)
    style_header(ws4)
    for _, row in merged.iterrows():
        ws4.append([row["essay_id"]] + [int(v) for v in row["content"]] +
                   [int(v) for v in row["org"]] + [int(v) for v in row["lang"]])
    autosize(ws4, [14] + [12] * 15)
    ws4.freeze_panes = "B2"

    wb.save(OUT_PATH)
    print(f"Saved -> {OUT_PATH}")


if __name__ == "__main__":
    main()
