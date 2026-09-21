"""
build_consolidated_singlesheet_workbook.py — ALL 200 essays (185 new + 15
reference) in ONE sheet, one row per essay, matching the provided example's
column layout:

  A Essay ID | B Band | C Essay Text
  D-H Content (Prof 1-5) | I Content Avg
  J-N Organization (Prof 1-5) | O Organization Avg
  P-T Language (Prof 1-5) | U Language Avg
  V Total (/15) | W Overall %

All 5 professors grade all 200 essays (multi-rater design).

Output: classification_model/dress_data/consolidated_singlesheet.xlsx (gitignored)
"""

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .build_professor_batch2_workbooks import PROFESSOR_SCORES_XLSX, SHARED_15, select_new_185
from .dress_pipeline import load_dress_bulk

REF_FILL = PatternFill("solid", fgColor="D9E1F2")  # distinguishes already-graded rows from blank ones


def load_reference_15_full_scores() -> dict:
    """essay_id -> {content: [5 scores], organization: [5], language: [5]} from the original xlsx."""
    wb = openpyxl.load_workbook(PROFESSOR_SCORES_XLSX, data_only=True)
    ws = wb["Scores"]
    rows = list(ws.iter_rows(min_row=3, max_row=17, values_only=True))
    out = {}
    for r in rows:
        out[r[0]] = {"content": list(r[2:7]), "organization": list(r[8:13]), "language": list(r[14:19])}
    return out

OUT_PATH = "classification_model/dress_data/consolidated_singlesheet_v2.xlsx"

FONT_NAME = "Arial"
HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
GROUP_FILL = PatternFill("solid", fgColor="2E75B6")
AVG_FILL = PatternFill("solid", fgColor="D9E1F2")
INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")
WHITE_BOLD = Font(name=FONT_NAME, bold=True, color="FFFFFF")
BOLD = Font(name=FONT_NAME, bold=True)
REGULAR = Font(name=FONT_NAME)
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT = Alignment(horizontal="left", vertical="top", wrap_text=True)

PROFESSORS = ["Professor 1", "Professor 2", "Professor 3", "Professor 4", "Professor 5"]
CRITERIA = ["CONTENT", "ORGANIZATION", "LANGUAGE"]
GROUP_START_COL = {"CONTENT": "D", "ORGANIZATION": "J", "LANGUAGE": "P"}
AVG_COL = {"CONTENT": "I", "ORGANIZATION": "O", "LANGUAGE": "U"}


def build_headers(ws):
    for col, label in [("A", "Essay ID"), ("B", "Band"), ("C", "Essay Text")]:
        ws.merge_cells(f"{col}1:{col}2")
        c = ws[f"{col}1"]
        c.value = label
        c.font = WHITE_BOLD
        c.fill = HEADER_FILL
        c.alignment = CENTER
        c.border = BORDER
        ws[f"{col}2"].border = BORDER
        ws[f"{col}2"].fill = HEADER_FILL

    for crit in CRITERIA:
        start = GROUP_START_COL[crit]
        start_idx = ws[f"{start}1"].column
        end_letter = get_column_letter(start_idx + 4)
        ws.merge_cells(f"{start}1:{end_letter}1")
        c = ws[f"{start}1"]
        c.value = crit
        c.font = WHITE_BOLD
        c.fill = GROUP_FILL
        c.alignment = CENTER
        c.border = BORDER
        for i, prof in enumerate(PROFESSORS):
            col_letter = get_column_letter(start_idx + i)
            cell = ws[f"{col_letter}2"]
            cell.value = prof
            cell.font = WHITE_BOLD
            cell.fill = GROUP_FILL
            cell.alignment = CENTER
            cell.border = BORDER

        avg_letter = AVG_COL[crit]
        ws.merge_cells(f"{avg_letter}1:{avg_letter}2")
        c = ws[f"{avg_letter}1"]
        c.value = f"{crit.title()}\nAvg"
        c.font = BOLD
        c.fill = AVG_FILL
        c.alignment = CENTER
        c.border = BORDER
        ws[f"{avg_letter}2"].border = BORDER
        ws[f"{avg_letter}2"].fill = AVG_FILL

    for col, label in [("V", "Total\n(/15)"), ("W", "Overall\n%")]:
        ws.merge_cells(f"{col}1:{col}2")
        c = ws[f"{col}1"]
        c.value = label
        c.font = BOLD
        c.fill = AVG_FILL
        c.alignment = CENTER
        c.border = BORDER
        ws[f"{col}2"].border = BORDER
        ws[f"{col}2"].fill = AVG_FILL

    ws.row_dimensions[1].height = 30
    ws.row_dimensions[2].height = 22


def build_essay_row(ws, row: int, essay_id: str, band: str, essay_text: str, dv: DataValidation,
                     prefilled: dict | None = None):
    """prefilled: {'content': [5 scores], 'organization': [5], 'language': [5]} — if given, the row
    is filled in and shaded as already-graded instead of left blank for new grading."""
    ws[f"A{row}"] = essay_id
    ws[f"A{row}"].font = BOLD
    ws[f"A{row}"].alignment = CENTER
    ws[f"A{row}"].border = BORDER
    ws[f"B{row}"] = band
    ws[f"B{row}"].font = BOLD
    ws[f"B{row}"].alignment = CENTER
    ws[f"B{row}"].border = BORDER
    ws[f"C{row}"] = essay_text
    ws[f"C{row}"].font = REGULAR
    ws[f"C{row}"].alignment = LEFT
    ws[f"C{row}"].border = BORDER

    fill = REF_FILL if prefilled else INPUT_FILL
    crit_key = {"CONTENT": "content", "ORGANIZATION": "organization", "LANGUAGE": "language"}
    for crit in CRITERIA:
        start = GROUP_START_COL[crit]
        start_idx = ws[f"{start}1"].column
        for i in range(5):
            col_letter = get_column_letter(start_idx + i)
            cell = ws[f"{col_letter}{row}"]
            if prefilled:
                cell.value = prefilled[crit_key[crit]][i]
            cell.fill = fill
            cell.font = REGULAR
            cell.alignment = CENTER
            cell.border = BORDER
            if not prefilled:
                dv.add(cell)
        avg_letter = AVG_COL[crit]
        end_letter = get_column_letter(start_idx + 4)
        avg_cell = ws[f"{avg_letter}{row}"]
        avg_cell.value = f'=IFERROR(AVERAGE({start}{row}:{end_letter}{row}),"")'
        avg_cell.font = BOLD
        avg_cell.alignment = CENTER
        avg_cell.border = BORDER

    total_cell = ws[f"V{row}"]
    total_cell.value = f'=IFERROR(I{row}+O{row}+U{row},"")'
    total_cell.font = BOLD
    total_cell.alignment = CENTER
    total_cell.border = BORDER

    pct_cell = ws[f"W{row}"]
    pct_cell.value = f'=IFERROR(V{row}/15*100,"")'
    pct_cell.number_format = "0.0"
    pct_cell.font = BOLD
    pct_cell.alignment = CENTER
    pct_cell.border = BORDER


def main():
    bulk = load_dress_bulk()
    new_185 = select_new_185()
    ref_scores = load_reference_15_full_scores()

    ref_essays = bulk[bulk["essay_id"].isin(SHARED_15)][["essay_id", "essay_text", "gt_band"]]
    ref_essays = ref_essays.set_index("essay_id").loc[SHARED_15].reset_index()  # preserve SHARED_15 order
    new_essays = bulk[bulk["essay_id"].isin(new_185["essay_id"])][["essay_id", "essay_text", "gt_band"]] \
        .sort_values("essay_id")

    print(f"Building 1 sheet: {len(ref_essays)} already-graded (top) + {len(new_essays)} new = "
          f"{len(ref_essays) + len(new_essays)} rows (expected 200)...")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Scores - Fill In"
    build_headers(ws)

    dv = DataValidation(type="whole", operator="between", formula1=1, formula2=5,
                         allow_blank=True, showErrorMessage=True,
                         errorTitle="Invalid score", error="Score must be a whole number from 1 to 5.")
    ws.add_data_validation(dv)

    row_num = 3
    for _, row in ref_essays.iterrows():
        build_essay_row(ws, row_num, row["essay_id"], row["gt_band"], row["essay_text"], dv,
                         prefilled=ref_scores[row["essay_id"]])
        row_num += 1
    for _, row in new_essays.iterrows():
        build_essay_row(ws, row_num, row["essay_id"], row["gt_band"], row["essay_text"], dv)
        row_num += 1

    ws.column_dimensions["A"].width = 13
    ws.column_dimensions["B"].width = 11
    ws.column_dimensions["C"].width = 60
    for col in "DEFGHJKLMNPQRST":
        ws.column_dimensions[col].width = 9
    for col in ["I", "O", "U"]:
        ws.column_dimensions[col].width = 10
    ws.column_dimensions["V"].width = 9
    ws.column_dimensions["W"].width = 9
    ws.freeze_panes = "D3"

    wb.save(OUT_PATH)
    print(f"Saved {OUT_PATH} ({row_num - 3} rows)")


if __name__ == "__main__":
    main()
