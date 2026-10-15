"""
selftest.py — CPU-only sanity checks for the pure-Python parts (no GPU, no
model download, no dataset download, writes nothing into the repo).

    python finetune/selftest.py
"""
import random
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from augment import augment, make_illegible
from build_imgur5k import crop_rotated
from common import cer, detokenize, id_exact_match, read_manifest, wer, write_manifest
from prompts import ABSTAIN_PROMPT, LIVE_PROMPT


def check(cond: bool, msg: str) -> None:
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        raise SystemExit(1)


def main() -> None:
    check(detokenize("Sir , the Mr . Smith do n't &quot;go&quot; ( yes )") == "Sir, the Mr. Smith don't \"go\" (yes)",
          "detokenize undoes IAM tokenization")
    check(cer("HELLO", "HELLO") == 0.0 and abs(cer("HELLO", "HELLA") - 0.2) < 1e-9, "cer")
    check(cer("Hello", "hello") > 0 and cer("Hello", "hello", True) == 0, "case-insensitive cer")
    check(abs(wer("a b c d", "a x c d") - 0.25) < 1e-9, "wer")
    check(id_exact_match(["Civil Disobedience"], "civil  disobedience"), "id match ignores case/whitespace")
    check(not id_exact_match(["Peace"], "Peace!"), "id match does NOT normalize punctuation")
    check(not id_exact_match(["Peace"], "peace", case_sensitive=True), "case-sensitive id match")
    check("[illegible]" in ABSTAIN_PROMPT and "[illegible]" not in LIVE_PROMPT, "abstain prompt differs")

    rng = random.Random(1)
    img = Image.fromarray(np.full((48, 300, 3), 235, np.uint8))
    arr = np.array(img)
    arr[18:30, 20:280] = 20
    img = Image.fromarray(arr)
    for i in range(20):
        a = augment(img, rng)
        check(a.mode == "RGB" and a.size[0] > 8 and a.size[1] > 8, f"augment {i} valid") if i in (0, 19) else None
    il = make_illegible(img, rng)
    check(il.size == img.size and il.mode == "RGB", "make_illegible keeps size")

    big = np.full((400, 600, 3), 255, np.uint8)
    big[180:220, 250:350] = 0
    crop = crop_rotated(big, (300, 200, 100, 40, 0.0), -1)
    check(crop is not None and crop.shape[:2] == (40, 100) and crop.mean() < 5, "imgur5k axis-aligned crop")
    check(crop_rotated(big, (5, 5, 50, 20, 30.0), -1) is not None, "imgur5k crop near border")

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "m.jsonl"
        rows = [{"id": "x", "image": "a.png", "text": "héllo", "source": "s", "split": "train", "kind": "normal"}]
        write_manifest(rows, p)
        check(read_manifest(p) == rows, "manifest roundtrip")
    print("All selftests passed.")


if __name__ == "__main__":
    main()
