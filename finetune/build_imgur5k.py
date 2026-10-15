"""
build_imgur5k.py — IMGUR5K word boxes -> cropped word images + manifest.

IMGUR5K (Facebook Research) ships image URLs and annotations only, under
CC BY-NC 4.0. Download the images first with the official script:

    git clone https://github.com/facebookresearch/IMGUR5K-Handwriting-Dataset
    cd IMGUR5K-Handwriting-Dataset
    python download_imgur5k.py --dataset_info_dir dataset_info --output_dir <IMAGES_DIR>

which also writes imgur5k_annotations.json. Then, from the repo root:

    python finetune/build_imgur5k.py --images-dir <IMAGES_DIR> \
        --annotations <path>/imgur5k_annotations.json --preview 20

Always run with --preview first and LOOK at finetune/artifacts/imgur5k_preview:
the rotated-box crop uses the convention (xc, yc, w, h, angle-in-degrees CCW)
and if the words come out tilted, rerun with --angle-sign 1 (default -1).
Images are not redistributed; only crops stay local under finetune/data/ (gitignored).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path

import cv2
import numpy as np

from common import ARTIFACTS_DIR, DATA_DIR, FT_DIR, write_manifest


def _parse_box(raw) -> tuple[float, float, float, float, float] | None:
    try:
        if isinstance(raw, str):
            raw = json.loads(raw)
        xc, yc, w, h, a = (float(v) for v in raw)
        return xc, yc, w, h, a
    except Exception:
        return None


def crop_rotated(img: np.ndarray, box, angle_sign: int) -> np.ndarray | None:
    xc, yc, w, h, a = box
    if w < 6 or h < 6:
        return None
    half = int(math.ceil(math.hypot(w, h) / 2)) + 2
    H, W = img.shape[:2]
    x0, y0 = int(round(xc)) - half, int(round(yc)) - half
    x1, y1 = x0 + 2 * half, y0 + 2 * half
    pad_l, pad_t = max(0, -x0), max(0, -y0)
    pad_r, pad_b = max(0, x1 - W), max(0, y1 - H)
    win = img[max(0, y0):min(H, y1), max(0, x0):min(W, x1)]
    if win.size == 0:
        return None
    if pad_l or pad_t or pad_r or pad_b:
        win = cv2.copyMakeBorder(win, pad_t, pad_b, pad_l, pad_r, cv2.BORDER_REPLICATE)
    M = cv2.getRotationMatrix2D((half, half), angle_sign * a, 1.0)
    rot = cv2.warpAffine(win, M, (2 * half, 2 * half), flags=cv2.INTER_CUBIC,
                         borderMode=cv2.BORDER_REPLICATE)
    cw, ch = int(round(w)), int(round(h))
    sx, sy = max(0, half - cw // 2), max(0, half - ch // 2)
    out = rot[sy:sy + ch, sx:sx + cw]
    return out if out.size else None


def _split_for(image_id: str, splits: dict[str, set[str]] | None) -> str:
    if splits:
        for name, ids in splits.items():
            if image_id in ids:
                return name
        return ""  # not in any official split -> skipped
    bucket = int(hashlib.md5(image_id.encode()).hexdigest(), 16) % 10
    return "train" if bucket < 8 else ("val" if bucket == 8 else "test")


def _read_ids(path: str | None) -> set[str] | None:
    if not path:
        return None
    return {ln.strip() for ln in Path(path).read_text().splitlines() if ln.strip()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images-dir", required=True)
    ap.add_argument("--annotations", required=True, help="imgur5k_annotations.json")
    ap.add_argument("--train-index"); ap.add_argument("--val-index"); ap.add_argument("--test-index")
    ap.add_argument("--max-words", type=int, default=0, help="0 = all; otherwise random subset")
    ap.add_argument("--angle-sign", type=int, default=-1, choices=(-1, 1))
    ap.add_argument("--preview", type=int, default=0, help="write N sample crops and exit")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    ann = json.loads(Path(args.annotations).read_text(encoding="utf-8"))
    index_to_ann = ann["index_to_ann_map"]
    ann_data = ann["ann_id"]

    splits = None
    if args.train_index or args.val_index or args.test_index:
        splits = {"train": _read_ids(args.train_index) or set(),
                  "val": _read_ids(args.val_index) or set(),
                  "test": _read_ids(args.test_index) or set()}

    items = []
    for image_id, ann_ids in index_to_ann.items():
        for aid in ann_ids:
            a = ann_data.get(aid)
            if not a:
                continue
            word = (a.get("word") or "").strip()
            box = _parse_box(a.get("bounding_box"))
            if not word or word == "." or box is None:   # '.' = not annotated
                continue
            items.append((image_id, aid, word, box))

    rng = random.Random(args.seed)
    rng.shuffle(items)
    if args.max_words:
        items = items[:args.max_words]
    if args.preview:
        items = items[:args.preview]
    print(f"{len(items)} candidate word boxes")

    images_dir = Path(args.images_dir)
    out_root = (ARTIFACTS_DIR / "imgur5k_preview") if args.preview else (DATA_DIR / "imgur5k")
    out_root.mkdir(parents=True, exist_ok=True)

    cache_id, cache_img = None, None
    rows, missing = [], 0
    for image_id, aid, word, box in sorted(items, key=lambda t: t[0]):
        if image_id != cache_id:
            p = next((q for q in (images_dir / f"{image_id}.jpg", images_dir / f"{image_id}.png",
                                  images_dir / f"{image_id}.jpeg") if q.exists()), None)
            cache_img = cv2.imread(str(p)) if p else None
            cache_id = image_id
        if cache_img is None:
            missing += 1
            continue
        split = _split_for(image_id, splits)
        if not split:
            continue
        crop = crop_rotated(cache_img, box, args.angle_sign)
        if crop is None:
            continue
        fname = f"{image_id}_{aid}.png"
        sub = out_root if args.preview else out_root / split
        sub.mkdir(parents=True, exist_ok=True)
        path = sub / fname
        cv2.imwrite(str(path), crop)
        if args.preview:
            print(f"  {fname}: {word!r}")
            continue
        rows.append({
            "id": f"imgur5k-{image_id}-{aid}",
            "image": str(path.relative_to(FT_DIR)).replace("\\", "/"),
            "text": word,
            "source": "imgur5k",
            "split": split,
            "kind": "normal",
        })

    if args.preview:
        print(f"Preview crops in {out_root}  (missing source images: {missing}). "
              f"If words are tilted, rerun with --angle-sign {-args.angle_sign}.")
        return
    out = DATA_DIR / "manifest_imgur5k.jsonl"
    write_manifest(rows, out)
    counts = {s: sum(r["split"] == s for r in rows) for s in ("train", "val", "test")}
    print(f"Wrote {len(rows)} rows to {out}  {counts}  (images not found: {missing})")


if __name__ == "__main__":
    main()
