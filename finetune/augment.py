"""
augment.py — synthetic variation for training crops.

Two jobs:
  augment()        make clean public-dataset lines look more like fast, slanted
                   handwriting photographed on a phone (slant, stroke weight,
                   blur, noise, shadow, JPEG). Applied to training rows only.
  make_illegible() turn a crop into something no reader could transcribe, to
                   be paired with the label "[illegible]".

Synthetic illegibility is not the same as genuinely hard handwriting: it
teaches "unreadable image -> abstain", and the real consented illegible crops
matter more. Run `python finetune/augment.py --preview <image>` to eyeball it.
"""
from __future__ import annotations

import random

import cv2
import numpy as np
from PIL import Image


def _bg_color(arr: np.ndarray) -> tuple[int, int, int]:
    flat = arr.reshape(-1, 3)
    return tuple(int(v) for v in np.median(flat, axis=0))


def augment(img: Image.Image, rng: random.Random) -> Image.Image:
    arr = np.array(img.convert("RGB"))
    h, w = arr.shape[:2]
    bg = _bg_color(arr)

    # Horizontal slant (shear) — fast handwriting leans.
    if rng.random() < 0.6:
        s = rng.uniform(-0.25, 0.25)
        new_w = int(w + abs(s) * h)
        shift = max(0.0, -s * h)
        M = np.float32([[1, s, shift], [0, 1, 0]])
        arr = cv2.warpAffine(arr, M, (new_w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=bg)
        h, w = arr.shape[:2]

    # Small rotation.
    if rng.random() < 0.5:
        ang = rng.uniform(-2.5, 2.5)
        M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
        arr = cv2.warpAffine(arr, M, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=bg)

    # Width squeeze/stretch — narrow, compressed writing.
    if rng.random() < 0.5:
        f = rng.uniform(0.8, 1.15)
        arr = cv2.resize(arr, (max(8, int(w * f)), h), interpolation=cv2.INTER_AREA)
        h, w = arr.shape[:2]

    # Stroke weight. Ink is dark, so erode (min filter) thickens, dilate thins.
    r = rng.random()
    if r < 0.25:
        arr = cv2.erode(arr, np.ones((2, 2), np.uint8), iterations=1)
    elif r < 0.4:
        arr = cv2.dilate(arr, np.ones((2, 2), np.uint8), iterations=1)

    # Soft focus / camera blur.
    if rng.random() < 0.4:
        sigma = rng.uniform(0.4, 1.3)
        arr = cv2.GaussianBlur(arr, (0, 0), sigma)

    f_arr = arr.astype(np.float32)

    # Brightness / contrast.
    if rng.random() < 0.6:
        alpha = rng.uniform(0.75, 1.25)
        beta = rng.uniform(-20, 20)
        f_arr = f_arr * alpha + beta

    # Soft shadow gradient (a fold or a hand's shadow).
    if rng.random() < 0.35:
        lo = rng.uniform(0.6, 0.95)
        if rng.random() < 0.5:
            ramp = np.linspace(1.0, lo, w, dtype=np.float32)[None, :, None]
        else:
            ramp = np.linspace(1.0, lo, h, dtype=np.float32)[:, None, None]
        f_arr = f_arr * ramp

    # Sensor noise.
    if rng.random() < 0.5:
        sigma = rng.uniform(2, 10)
        noise = np.random.default_rng(rng.randrange(2**32)).normal(0, sigma, f_arr.shape)
        f_arr = f_arr + noise.astype(np.float32)

    arr = np.clip(f_arr, 0, 255).astype(np.uint8)

    # JPEG artefacts from phone cameras / messaging apps.
    if rng.random() < 0.4:
        q = rng.randint(35, 90)
        ok, buf = cv2.imencode(".jpg", cv2.cvtColor(arr, cv2.COLOR_RGB2BGR),
                               [cv2.IMWRITE_JPEG_QUALITY, q])
        if ok:
            arr = cv2.cvtColor(cv2.imdecode(buf, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)

    # Random margin.
    if rng.random() < 0.5:
        pad = rng.randint(2, 14)
        arr = cv2.copyMakeBorder(arr, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=bg)

    return Image.fromarray(arr)


def make_illegible(img: Image.Image, rng: random.Random) -> Image.Image:
    """Destroy the text so it cannot be read, keeping a realistic page look."""
    arr = np.array(img.convert("RGB"))
    h, w = arr.shape[:2]
    gen = np.random.default_rng(rng.randrange(2**32))

    if rng.random() < 0.5:
        # Smear: collapse to a few pixels of height, then blow back up.
        tiny_h = max(2, h // rng.randint(10, 18))
        tiny_w = max(4, w // rng.randint(14, 26))
        small = cv2.resize(arr, (tiny_w, tiny_h), interpolation=cv2.INTER_AREA)
        arr = cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)
        arr = cv2.GaussianBlur(arr, (0, 0), rng.uniform(3.0, 5.5))
    else:
        # Scribble: dense overwritten strokes, as when a line is written over.
        ink = tuple(int(v) for v in np.percentile(arr.reshape(-1, 3), 5, axis=0))
        canvas = arr.copy()
        for _ in range(rng.randint(8, 18)):
            n = rng.randint(4, 9)
            xs = np.sort(gen.integers(0, max(2, w), n))
            ys = gen.integers(0, max(2, h), n)
            pts = np.stack([xs, ys], axis=1).astype(np.int32).reshape(-1, 1, 2)
            thickness = max(1, int(h * rng.uniform(0.06, 0.18)))
            cv2.polylines(canvas, [pts], False, ink, thickness, cv2.LINE_AA)
        arr = cv2.GaussianBlur(canvas, (0, 0), rng.uniform(0.8, 1.6))

    noise = gen.normal(0, rng.uniform(3, 9), arr.shape)
    arr = np.clip(arr.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    ap = argparse.ArgumentParser(description="Write augmented / illegible previews of one image.")
    ap.add_argument("--preview", required=True, help="input image")
    ap.add_argument("--out-dir", default="finetune/artifacts/augment_preview")
    ap.add_argument("--n", type=int, default=6)
    args = ap.parse_args()

    src = Image.open(args.preview).convert("RGB")
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    r = random.Random(0)
    for i in range(args.n):
        augment(src, r).save(out / f"aug_{i}.png")
    for i in range(args.n):
        make_illegible(src, r).save(out / f"illegible_{i}.png")
    print(f"Wrote {args.n} augmented and {args.n} illegible previews to {out}")
