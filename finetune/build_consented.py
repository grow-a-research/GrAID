"""
build_consented.py — consented handwriting samples -> manifest.

Folder layout (gitignored; create it yourself):

    finetune/consented/
        sample_001.png     the crop of ONE line / short segment
        sample_001.txt     its verified transcription, exactly as written
        sample_002.jpg
        sample_002.txt     containing exactly:  [illegible]   for unreadable crops
        ...

Rules agreed with the writers: usable, never attributed. Use neutral file
names (no names, initials or exam/student identifiers). Labels are written by
a human who can vouch for them — never from a model's reading. Crop out
numbering marks and emphatic "!" so the label matches the pixels.

Split: every Nth file (sorted by name) is held out as `test` and is never
trained on, so a before/after on these writers is honest. With so few lines
this is a qualitative check, not a statistic.

    python finetune/build_consented.py [--holdout-every 3] [--expect-upper]
"""
from __future__ import annotations

import argparse

from common import CONSENTED_DIR, DATA_DIR, FT_DIR, ILLEGIBLE, write_manifest

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(CONSENTED_DIR))
    ap.add_argument("--holdout-every", type=int, default=3,
                    help="every Nth file goes to the held-out test split")
    ap.add_argument("--expect-upper", action="store_true",
                    help="warn when a label contains lowercase letters")
    args = ap.parse_args()

    from pathlib import Path
    root = Path(args.dir)
    if not root.is_dir():
        raise SystemExit(f"{root} does not exist. Create it and add <name>.png + <name>.txt pairs "
                         f"(see this file's docstring). The folder is gitignored.")

    images = sorted(p for p in root.iterdir() if p.suffix.lower() in IMG_EXT)
    rows, problems = [], []
    for n, img in enumerate(images):
        txt = img.with_suffix(".txt")
        if not txt.exists():
            problems.append(f"{img.name}: no matching .txt")
            continue
        label = " ".join(txt.read_text(encoding="utf-8").split())
        if not label:
            problems.append(f"{img.name}: empty label")
            continue
        kind = "normal"
        if label.casefold() == ILLEGIBLE:
            label, kind = ILLEGIBLE, "illegible"
        elif args.expect_upper and any(c.islower() for c in label):
            problems.append(f"{img.name}: label has lowercase letters: {label!r}")
        split = "test" if (n % args.holdout_every) == (args.holdout_every - 1) else "train"
        rows.append({
            "id": f"consented-{img.stem}",
            "image": str(img.relative_to(FT_DIR)).replace("\\", "/") if img.is_relative_to(FT_DIR)
                     else str(img),
            "text": label,
            "source": "consented",
            "split": split,
            "kind": kind,
        })

    for p in problems:
        print("WARNING:", p)
    out = DATA_DIR / "manifest_consented.jsonl"
    write_manifest(rows, out)
    c = {s: sum(r["split"] == s for r in rows) for s in ("train", "test")}
    ill = sum(r["kind"] == "illegible" for r in rows)
    print(f"Wrote {len(rows)} rows to {out}  {c}  (illegible: {ill})")
    if c["test"] == 0:
        print("NOTE: no held-out lines; add more files or lower --holdout-every.")


if __name__ == "__main__":
    main()
