"""
build_professor_batch2_workbooks.py — builds 5 per-professor Excel workbooks
for the second round of professor grading (185 new essays, 37 per
professor, single-rater / non-overlapping — not the multi-rater design
used for the original 15).

Each workbook has 3 tabs:
  1. Instructions
  2. Reference Examples — the original 15 essays, already graded (shown
     with their consensus average scores, locked/read-only) so professors
     have a familiar, already-completed example before grading new ones.
  3. Your Essays - Fill In — this professor's 37 new essays, blank score
     columns.

Essay selection: 185 essays stratified proportionally to the real DREsS
band distribution, drawn from the eligible pool EXCLUDING the 15 already
used. Each professor's 37-essay block is ALSO internally stratified (not
a contiguous chunk of one band) — every professor gets a representative
mix of Poor/Fair/Good/Excellent, avoiding the imbalance bug found earlier
when Groq-account shards were split as contiguous blocks.

Output: classification_model/dress_data/professor_batch2_profN.xlsx (gitignored)
"""

import openpyxl
import pandas as pd
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .dress_pipeline import load_dress_bulk

SHARED_15 = [
    "DRESS-1790", "DRESS-1781", "DRESS-1779", "DRESS-1777", "DRESS-1432",
    "DRESS-2151", "DRESS-1450", "DRESS-1685", "DRESS-1778", "DRESS-1449",
    "DRESS-1412", "DRESS-1664", "DRESS-1652", "DRESS-1433", "DRESS-2193",
]
PROFESSOR_SCORES_XLSX = r"C:\Users\ASUS\Downloads\DREsS Score .xlsx"

N_NEW = 185
N_PROFESSORS = 5
SEED = 99
OUT_DIR = "classification_model/dress_data"

FONT_NAME = "Arial"
HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
REF_FILL = PatternFill("solid", fgColor="D9E1F2")
INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")
WHITE_BOLD = Font(name=FONT_NAME, bold=True, color="FFFFFF")
BOLD = Font(name=FONT_NAME, bold=True)
REGULAR = Font(name=FONT_NAME)
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT = Alignment(horizontal="left", vertical="top", wrap_text=True)


def load_reference_15() -> pd.DataFrame:
    """The original 15, with their consensus (average) per-criterion scores."""
    wb = openpyxl.load_workbook(PROFESSOR_SCORES_XLSX, data_only=True)
    ws = wb["Scores"]
    rows = list(ws.iter_rows(min_row=3, max_row=17, values_only=True))
    scores = pd.DataFrame([
        {"essay_id": r[0], "content_avg": r[7], "organization_avg": r[13], "language_avg": r[19]}
        for r in rows
    ])
    bulk = load_dress_bulk()
    return scores.merge(bulk[["essay_id", "question_prompt", "essay_text"]], on="essay_id", how="left")


def select_new_185() -> pd.DataFrame:
    bulk = load_dress_bulk()
    pool = bulk[~bulk["essay_id"].isin(SHARED_15)].copy()

    band_counts = pool["gt_band"].value_counts()
    proportions = band_counts / band_counts.sum()
    per_band_n = (proportions * N_NEW).round().astype(int)
    drift = N_NEW - per_band_n.sum()
    if drift != 0:
        per_band_n[per_band_n.idxmax()] += drift

    parts = [
        pool[pool["gt_band"] == band].sample(n=count, random_state=SEED)
        for band, count in per_band_n.items() if count > 0
    ]
    return pd.concat(parts, ignore_index=True)


def split_into_professor_blocks(sample: pd.DataFrame, n_professors: int) -> list[pd.DataFrame]:
    """
    Split `sample` into n_professors blocks, each INTERNALLY stratified —
    every professor gets a proportional mix of every band, not a
    contiguous chunk of one band.
    """
    blocks: list[list] = [[] for _ in range(n_professors)]
    for band in sample["gt_band"].unique():
        band_rows = sample[sample["gt_band"] == band].sample(frac=1, random_state=SEED).to_dict("records")
        for i, row in enumerate(band_rows):
            blocks[i % n_professors].append(row)
    return [pd.DataFrame(b) for b in blocks]


def style_header(ws, cell_ref, text, fill=HEADER_FILL, font=WHITE_BOLD):
    c = ws[cell_ref]
    c.value = text
    c.fill = fill
    c.font = font
    c.alignment = CENTER
    c.border = BORDER


def build_reference_sheet(wb, reference_df: pd.DataFrame):
    ws = wb.create_sheet("Reference Examples")
    headers = ["Essay ID", "Essay Text", "Content", "Organization", "Language"]
    for i, h in enumerate(headers, start=1):
        style_header(ws, f"{get_column_letter(i)}1", h)
    for r, (_, row) in enumerate(reference_df.iterrows(), start=2):
        ws.cell(row=r, column=1, value=row["essay_id"]).font = REGULAR
        ws.cell(row=r, column=1).alignment = CENTER
        ws.cell(row=r, column=2, value=row["essay_text"]).font = REGULAR
        ws.cell(row=r, column=2).alignment = LEFT
        for col, key in [(3, "content_avg"), (4, "organization_avg"), (5, "language_avg")]:
            cell = ws.cell(row=r, column=col, value=row[key])
            cell.font = BOLD
            cell.alignment = CENTER
            cell.fill = REF_FILL
        for col in range(1, 6):
            ws.cell(row=r, column=col).border = BORDER
    ws.column_dimensions["A"].width = 13
    ws.column_dimensions["B"].width = 80
    for col in "CDE":
        ws.column_dimensions[col].width = 12
    ws.freeze_panes = "A2"
    note = ws.cell(row=len(reference_df) + 3, column=1,
                    value="These 15 were already graded by all 5 professors previously. Scores shown "
                          "here are the average across all 5. This tab is for reference/familiarization "
                          "only — do not edit.")
    note.font = Font(name=FONT_NAME, italic=True, size=9)
    ws.merge_cells(start_row=note.row, start_column=1, end_row=note.row, end_column=5)


def build_fill_in_sheet(wb, professor_df: pd.DataFrame, professor_num: int):
    ws = wb.active
    ws.title = "Your Essays - Fill In"
    headers = ["Essay ID", "Essay Text", "Content (1-5)", "Organization (1-5)", "Language (1-5)"]
    for i, h in enumerate(headers, start=1):
        style_header(ws, f"{get_column_letter(i)}1", h)

    dv = DataValidation(type="whole", operator="between", formula1=1, formula2=5,
                         allow_blank=True, showErrorMessage=True,
                         errorTitle="Invalid score", error="Score must be a whole number from 1 to 5.")
    ws.add_data_validation(dv)

    for r, (_, row) in enumerate(professor_df.iterrows(), start=2):
        ws.cell(row=r, column=1, value=row["essay_id"]).font = REGULAR
        ws.cell(row=r, column=1).alignment = CENTER
        ws.cell(row=r, column=2, value=row["essay_text"]).font = REGULAR
        ws.cell(row=r, column=2).alignment = LEFT
        for col in (3, 4, 5):
            cell = ws.cell(row=r, column=col)
            cell.fill = INPUT_FILL
            cell.alignment = CENTER
            dv.add(cell)
        for col in range(1, 6):
            ws.cell(row=r, column=col).border = BORDER

    ws.column_dimensions["A"].width = 13
    ws.column_dimensions["B"].width = 80
    for col in "CDE":
        ws.column_dimensions[col].width = 16
    ws.freeze_panes = "A2"


def build_instructions_sheet(wb, professor_num: int, n_essays: int):
    ws = wb.create_sheet("Instructions", 0)
    ws.sheet_view.showGridLines = False
    title = ws.cell(row=1, column=1, value=f"Professor {professor_num} — Essay Grading Batch 2")
    title.font = Font(name=FONT_NAME, bold=True, size=14)

    lines = [
        "",
        f"This workbook contains {n_essays} NEW essays assigned only to you — no other professor is "
        "grading these same essays, so there's no need to coordinate scores with anyone else this time.",
        "",
        "1. Start with the \"Reference Examples\" tab — these are the same 15 essays "
        "from the earlier round, already scored, shown here just so you can recall the rubric and "
        "scoring style before grading the new ones. Do not edit that tab.",
        "2. Go to \"Your Essays - Fill In\" and score each essay's Content, Organization, and Language "
        "(1-5 each), same rubric as before (see GRAID-RUBRICS.pdf).",
        "3. Only edit the YELLOW cells. A dropdown will reject anything outside 1-5.",
        "4. Read each essay directly in this file (Essay Text column) — no separate PDF this time.",
        "",
        "Thank you for helping with this second round!",
    ]
    for i, line in enumerate(lines, start=2):
        cell = ws.cell(row=i, column=1, value=line)
        cell.font = REGULAR
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=i, start_column=1, end_row=i, end_column=6)
        ws.row_dimensions[i].height = 30 if len(line) > 90 else (16 if line else 8)
    ws.column_dimensions["A"].width = 14
    for col in "BCDEF":
        ws.column_dimensions[col].width = 14


def main():
    reference_15 = load_reference_15()
    new_185 = select_new_185()
    blocks = split_into_professor_blocks(new_185, N_PROFESSORS)

    for i, block in enumerate(blocks, start=1):
        print(f"Professor {i}: {len(block)} essays, bands: {block['gt_band'].value_counts().to_dict()}")
        wb = openpyxl.Workbook()
        build_fill_in_sheet(wb, block, i)
        build_reference_sheet(wb, reference_15)
        build_instructions_sheet(wb, i, len(block))
        out_path = f"{OUT_DIR}/professor_batch2_prof{i}.xlsx"
        wb.save(out_path)
        print(f"  Saved {out_path}")


if __name__ == "__main__":
    main()
