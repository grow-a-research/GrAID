"""
build_iam.py — IAM handwriting lines -> training manifest.

Source: the Hugging Face release Teklia/IAM-line, which repackages the IAM
Handwriting Database line images (Marti & Bunke, IJDAR 2002). Terms of the
original database apply (non-commercial research); cite IAM and say it was
obtained via the Teklia release. The train/validation/test partitions are the
ones Teklia ships — not verified to equal the official IAM partitions, so do
not call them that.

    python finetune/build_iam.py [--revision <commit>] [--max-per-split 2000]

Writes images to finetune/data/iam/<split>/ and finetune/data/manifest_iam.jsonl.
"""
from __future__ import annotations

import argparse
import random

from common import DATA_DIR, FT_DIR, detokenize, write_manifest

SPLIT_MAP = {"train": "train", "validation": "val", "val": "val", "test": "test"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="Teklia/IAM-line")
    ap.add_argument("--revision", default=None, help="pin a dataset commit for reproducibility")
    ap.add_argument("--max-per-split", type=int, default=0, help="0 = all")
    ap.add_argument("--no-detokenize", action="store_true",
                    help="keep IAM's tokenized spacing (not recommended)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    from datasets import load_dataset

    ds = load_dataset(args.dataset, revision=args.revision)
    rng = random.Random(args.seed)
    rows: list[dict] = []
    shown = 0

    for hf_split, split in SPLIT_MAP.items():
        if hf_split not in ds:
            continue
        part = ds[hf_split]
        cols = part.column_names
        img_col = "image" if "image" in cols else next(c for c in cols if c != "text")
        txt_col = "text" if "text" in cols else next(c for c in cols if c != img_col)
        idxs = list(range(len(part)))
        if args.max_per_split and len(idxs) > args.max_per_split:
            idxs = sorted(rng.sample(idxs, args.max_per_split))

        out_dir = DATA_DIR / "iam" / split
        out_dir.mkdir(parents=True, exist_ok=True)
        for i in idxs:
            ex = part[i]
            raw = (ex[txt_col] or "").strip()
            text = raw if args.no_detokenize else detokenize(raw)
            if not text:
                continue
            path = out_dir / f"{i:06d}.png"
            ex[img_col].convert("RGB").save(path)
            rows.append({
                "id": f"iam-{split}-{i:06d}",
                "image": str(path.relative_to(FT_DIR)).replace("\\", "/"),
                "text": text,
                "source": "iam",
                "split": split,
                "kind": "normal",
            })
            if shown < 5 and raw != text:
                print(f"  detokenized: {raw!r} -> {text!r}")
                shown += 1

    out = DATA_DIR / "manifest_iam.jsonl"
    write_manifest(rows, out)
    counts = {s: sum(r["split"] == s for r in rows) for s in ("train", "val", "test")}
    print(f"Wrote {len(rows)} IAM rows to {out}  {counts}")
    print("Inspect a few labels before training; punctuation spacing matters for exact-match scoring.")


if __name__ == "__main__":
    main()
