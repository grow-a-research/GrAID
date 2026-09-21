"""
Restore the deleted PSE MCQ/TF exam (exam 3) from data/app_backup_2026-09-19.db
into the live data/app.db.

Safety design
-------------
* INSERT-ONLY. The script issues no UPDATE and no DELETE against the live DB.
* Aborts before writing if ANY id it would insert already exists live.
* Runs inside one transaction; any problem rolls the whole thing back.
* Fingerprints every pre-existing row before and after the insert and refuses
  to commit unless the two fingerprints match exactly.
* Dry-run by default. Pass --apply to actually write.

By default this restores only the exam SHELL -- the exam row (including its
original template_spec_json) and its 30 questions with their bubble regions
and answer keys -- so submissions can simply be re-uploaded.

The PSE class itself was never deleted; class 3 and its 27 enrollments are
still live, so nothing is inserted there.

Pass --with-submissions to also restore the 25 old submissions and their 750
graded answers. The 25 scan images are gone from disk either way.

Usage:
    python eval/restore_mcqtf_exam3.py                    # dry run
    python eval/restore_mcqtf_exam3.py --apply            # restore exam + questions
    python eval/restore_mcqtf_exam3.py --apply --with-submissions
"""
from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path

BACKUP = Path("data/app_backup_2026-09-19.db")
LIVE = Path("data/app.db")
EXAM_ID = 3

# Tables copied, in foreign-key-safe order.
SHELL_TABLES = ["exams", "exam_questions"]
SUBMISSION_TABLES = ["submissions", "submission_files",
                     "submission_answers", "flag_log"]

WITH_SUBS = "--with-submissions" in sys.argv
TABLES = SHELL_TABLES + (SUBMISSION_TABLES if WITH_SUBS else [])

# Tables that must not change at all (we insert nothing into them).
UNTOUCHED = ["course_classes", "students", "enrollments", "alembic_version"]
if not WITH_SUBS:
    UNTOUCHED = UNTOUCHED + SUBMISSION_TABLES

APPLY = "--apply" in sys.argv


def rows_for(con: sqlite3.Connection) -> dict[str, list[sqlite3.Row]]:
    """Every backup row belonging to exam 3, keyed by table."""
    sub_ids = [r[0] for r in con.execute(
        "SELECT id FROM submissions WHERE exam_id=?", (EXAM_ID,))]
    subq = "(" + ",".join("?" * len(sub_ids)) + ")" if sub_ids else "(NULL)"

    out: dict[str, list[sqlite3.Row]] = {}
    out["exams"] = con.execute(
        "SELECT * FROM exams WHERE id=?", (EXAM_ID,)).fetchall()
    out["exam_questions"] = con.execute(
        "SELECT * FROM exam_questions WHERE exam_id=? ORDER BY id", (EXAM_ID,)).fetchall()
    out["submissions"] = con.execute(
        "SELECT * FROM submissions WHERE exam_id=? ORDER BY id", (EXAM_ID,)).fetchall()
    out["submission_files"] = con.execute(
        f"SELECT * FROM submission_files WHERE submission_id IN {subq} ORDER BY id",
        sub_ids).fetchall()
    out["submission_answers"] = con.execute(
        f"SELECT * FROM submission_answers WHERE submission_id IN {subq} ORDER BY id",
        sub_ids).fetchall()
    out["flag_log"] = con.execute(
        f"SELECT * FROM flag_log WHERE submission_answer_id IN "
        f"(SELECT id FROM submission_answers WHERE submission_id IN {subq}) ORDER BY id",
        sub_ids).fetchall()
    return out


def fingerprint(con: sqlite3.Connection, skip: dict[str, set[int]]) -> str:
    """SHA-256 over every row in the live DB, excluding ids we are inserting."""
    h = hashlib.sha256()
    for table in TABLES + UNTOUCHED:
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
        order = "id" if "id" in cols else cols[0]
        h.update(f"|TABLE {table}|".encode())
        for row in con.execute(f"SELECT * FROM {table} ORDER BY {order}"):
            if "id" in cols and row[cols.index("id")] in skip.get(table, set()):
                continue
            h.update(repr(tuple(row)).encode())
    return h.hexdigest()


def main() -> int:
    if not BACKUP.exists() or not LIVE.exists():
        print("ERROR: database file missing")
        return 1

    src = sqlite3.connect(f"file:{BACKUP}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    data = rows_for(src)

    dst = sqlite3.connect(LIVE)
    dst.row_factory = sqlite3.Row
    dst.execute("PRAGMA foreign_keys=ON")

    # ---- Pre-flight: refuse to touch anything that already exists ----------
    incoming: dict[str, set[int]] = {}
    collisions = []
    for table in TABLES:
        cols = [r[1] for r in dst.execute(f"PRAGMA table_info({table})")]
        if "id" not in cols:
            continue
        ids = {r["id"] for r in data[table]}
        incoming[table] = ids
        if ids:
            q = "(" + ",".join("?" * len(ids)) + ")"
            hit = [r[0] for r in dst.execute(
                f"SELECT id FROM {table} WHERE id IN {q}", tuple(ids))]
            if hit:
                collisions.append((table, hit))

    scope = "exam + questions + submissions" if WITH_SUBS else "exam + questions ONLY (re-upload scans yourself)"
    print(f"{'DRY RUN - nothing will be written' if not APPLY else 'APPLYING RESTORE'}")
    print(f"Scope:  {scope}")
    print(f"Source: {BACKUP}\nTarget: {LIVE}\n")
    for table in TABLES:
        print(f"  {table:<20} {len(data[table]):>5} rows to insert")
    print()

    if collisions:
        print("ABORT — these ids already exist in the live database:")
        for table, hit in collisions:
            print(f"  {table}: {hit[:10]}{' ...' if len(hit) > 10 else ''}")
        return 1
    print("Pre-flight OK: no id collisions.\n")

    before = fingerprint(dst, incoming)
    print(f"Fingerprint of existing data (before): {before[:16]}...")

    if not APPLY:
        print("\nDry run complete. Re-run with --apply to perform the restore.")
        return 0

    try:
        dst.execute("BEGIN IMMEDIATE")
        for table in TABLES:
            if not data[table]:
                continue
            live_cols = [r[1] for r in dst.execute(f"PRAGMA table_info({table})")]
            src_cols = data[table][0].keys()
            use = [c for c in live_cols if c in src_cols]
            placeholders = ",".join("?" * len(use))
            sql = f"INSERT INTO {table} ({','.join(use)}) VALUES ({placeholders})"
            dst.executemany(sql, [tuple(r[c] for c in use) for r in data[table]])
            print(f"  inserted {len(data[table]):>5} into {table}")

        after = fingerprint(dst, incoming)
        if after != before:
            dst.execute("ROLLBACK")
            print("\nABORT — existing data changed. Rolled back, nothing written.")
            return 1

        integrity = dst.execute("PRAGMA integrity_check").fetchone()[0]
        fk = dst.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or fk:
            dst.execute("ROLLBACK")
            print(f"\nABORT — integrity={integrity} fk_violations={len(fk)}. Rolled back.")
            return 1

        dst.execute("COMMIT")
        print(f"\nFingerprint of existing data (after):  {after[:16]}...  MATCH")
        print("Existing data verified unchanged. Restore committed.")
    except Exception as exc:
        dst.execute("ROLLBACK")
        print(f"\nERROR: {exc}\nRolled back — nothing written.")
        return 1

    print(f"\nExam {EXAM_ID} restored. Note: the 25 scan images are still missing "
          f"from disk — restore them from the OneDrive recycle bin if needed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
