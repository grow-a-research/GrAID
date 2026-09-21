"""
build_replacement_28_workbook.py — builds a grading workbook for 28
replacement essays, to send to the 5 GenEd professors for fresh grading.

These 28 replace the essays being dropped from the 200-essay training set:
  - 16 confirmed off-topic essays (essay content doesn't match its assigned
    question prompt — a source-corpus mislabeling defect, see
    project_graid_essay_collection_design memory)
  - 12 essays whose re-grade (grade_CoordinatorGenEd.xlsx) showed unreliable
    statistical patterns (near-identical scores across all 5 "independent"
    raters, implausible score swings) — their ORIGINAL scores are kept for
    now, but replacing them entirely sidesteps the question altogether.

Same single-sheet layout as the original consolidated workbook (Essay ID |
Band | Essay Text | Content x5 + Avg | Organization x5 + Avg | Language x5
+ Avg | Total | Overall %) for direct compatibility with how the
professors already grade.

Selection: 28 essays stratified proportionally to DREsS's own band
distribution (same method used for the original 185), drawn from the pool
excluding all 228 essays already used or replaced (200 current + the 28
being newly picked, naturally) and the essays already flagged as
problematic.

Output: classification_model/dress_data/replacement_28_workbook.xlsx (gitignored)
"""

import openpyxl

from .build_consolidated_singlesheet_workbook import build_essay_row, build_headers
from .build_professor_batch2_workbooks import SHARED_15
from .dress_pipeline import load_dress_bulk, select_stratified_sample
from openpyxl.worksheet.datavalidation import DataValidation

# The 28 essays being replaced (16 off-topic + 12 unreliable-re-grade, no overlap kept once)
OFFTOPIC_16 = [
    "DRESS-1126", "DRESS-1231", "DRESS-1235", "DRESS-353", "DRESS-34",
    "DRESS-631", "DRESS-633", "DRESS-634", "DRESS-636", "DRESS-644", "DRESS-969",
    "DRESS-1050", "DRESS-1061", "DRESS-1062", "DRESS-1066", "DRESS-1109",
]
UNRELIABLE_REGRADE_12 = [
    "DRESS-1016", "DRESS-1056", "DRESS-1163", "DRESS-1401", "DRESS-1731", "DRESS-1987",
    "DRESS-2005", "DRESS-2172", "DRESS-587", "DRESS-593", "DRESS-766", "DRESS-906",
]
REPLACING = sorted(set(OFFTOPIC_16) | set(UNRELIABLE_REGRADE_12))

N_REPLACEMENTS = 28
SEED = 202
OUT_PATH = "classification_model/dress_data/replacement_28_workbook.xlsx"


def select_replacement_essays():
    bulk = load_dress_bulk()
    # exclude the full current 200-essay pool (SHARED_15 + the 185 new, which
    # includes the 28 being replaced) so nothing gets picked twice
    from .build_professor_batch2_workbooks import select_new_185
    current_200 = set(SHARED_15) | set(select_new_185()["essay_id"])
    pool = bulk[~bulk["essay_id"].isin(current_200)]
    return select_stratified_sample(pool, N_REPLACEMENTS, seed=SEED)


def main():
    print(f"Essays being replaced ({len(REPLACING)}): {REPLACING}")
    replacements = select_replacement_essays()
    print(f"\nSelected {len(replacements)} replacement essays, band distribution:")
    print(replacements["gt_band"].value_counts())

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Scores - Fill In"
    build_headers(ws)

    dv = DataValidation(type="whole", operator="between", formula1=1, formula2=5,
                         allow_blank=True, showErrorMessage=True,
                         errorTitle="Invalid score", error="Score must be a whole number from 1 to 5.")
    ws.add_data_validation(dv)

    row_num = 3
    for _, row in replacements.sort_values("essay_id").iterrows():
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
    print(f"\nSaved {OUT_PATH} ({row_num - 3} rows)")

    # Save the exact list of replacement essay_ids so the AI-grading and
    # merge scripts can reference the same set later, deterministically.
    ids_path = "classification_model/dress_data/replacement_28_ids.txt"
    with open(ids_path, "w") as f:
        f.write("\n".join(replacements["essay_id"].tolist()))
    print(f"Saved essay ID list -> {ids_path}")


if __name__ == "__main__":
    main()
