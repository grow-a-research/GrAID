"""
common.py — helpers shared by the fine-tuning scripts.

Imports nothing from the live app. Heavy dependencies (torch, transformers)
are imported lazily so the dataset builders and selftest run on a laptop.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

FT_DIR = Path(__file__).resolve().parent
DATA_DIR = FT_DIR / "data"
ARTIFACTS_DIR = FT_DIR / "artifacts"
CONSENTED_DIR = FT_DIR / "consented"

DEFAULT_BASE_MODEL = "Qwen/Qwen2.5-VL-7B-Instruct"
ILLEGIBLE = "[illegible]"


# ---------------------------------------------------------------------------
# Manifests: one JSON object per line.
#   id, image (path relative to finetune/), text, source, split, kind
#   split in {train, val, test}; kind in {normal, illegible}
# ---------------------------------------------------------------------------

def write_manifest(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_manifest(path: Path) -> list[dict]:
    rows = []
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_manifests(paths: list[str], split: str | None = None) -> list[dict]:
    rows: list[dict] = []
    for p in paths:
        rows.extend(read_manifest(Path(p)))
    if split is not None:
        rows = [r for r in rows if r["split"] == split]
    return rows


# ---------------------------------------------------------------------------
# Text cleanup and metrics
# ---------------------------------------------------------------------------

_DETOK = [
    (re.compile(r"\s+([,.;:!?%)\]])"), r"\1"),
    (re.compile(r"([(\[$£])\s+"), r"\1"),
    (re.compile(r"(\w)\s+(n't|'s|'ll|'re|'ve|'d|'m)\b", re.I), r"\1\2"),
]


def detokenize(text: str) -> str:
    """
    IAM transcriptions are word-tokenized ("Sir , the" / "do n't"). Handwriting
    is not, and the identification scorer does not normalize punctuation, so
    training on tokenized spacing would teach the model to emit spaces that
    are not on the page. Undo the tokenization and unescape HTML entities.
    """
    text = html.unescape(text)
    for pattern, repl in _DETOK:
        text = pattern.sub(repl, text)
    return " ".join(text.split())


def _lev(a, b) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _flat(s: str) -> str:
    return " ".join((s or "").split())


def cer(ref: str, hyp: str, case_insensitive: bool = False) -> float:
    ref, hyp = _flat(ref), _flat(hyp)
    if case_insensitive:
        ref, hyp = ref.casefold(), hyp.casefold()
    return _lev(ref, hyp) / max(1, len(ref))


def wer(ref: str, hyp: str, case_insensitive: bool = False) -> float:
    r, h = _flat(ref), _flat(hyp)
    if case_insensitive:
        r, h = r.casefold(), h.casefold()
    rw, hw = r.split(), h.split()
    return _lev(rw, hw) / max(1, len(rw))


def id_exact_match(accepted: list[str], given: str, case_sensitive: bool = False) -> bool:
    """Mirror of identification_scoring: trim/collapse whitespace, optional
    case-folding, nothing else normalized (punctuation counts)."""
    norm = (lambda t: _flat(t)) if case_sensitive else (lambda t: _flat(t).casefold())
    g = norm(given)
    return bool(g) and any(norm(a) == g for a in accepted)


# ---------------------------------------------------------------------------
# Model loading and prompt construction (GPU side; lazy imports)
# ---------------------------------------------------------------------------

def build_messages(image, prompt: str) -> list[dict]:
    return [{
        "role": "user",
        "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt}],
    }]


def load_model_and_processor(base_model: str = DEFAULT_BASE_MODEL, quant: str = "bf16",
                             adapter: str | None = None):
    import torch
    from transformers import AutoProcessor
    try:
        from transformers import AutoModelForImageTextToText as AutoVLM
    except ImportError:  # older transformers
        from transformers import AutoModelForVision2Seq as AutoVLM

    kwargs: dict = {"torch_dtype": torch.bfloat16, "device_map": {"": 0}, "trust_remote_code": True}
    if quant == "4bit":
        from transformers import BitsAndBytesConfig
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16)
    elif quant == "8bit":
        from transformers import BitsAndBytesConfig
        kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)
    elif quant not in ("bf16", "none"):
        raise SystemExit(f"Unknown --quant {quant!r}; use bf16, 8bit or 4bit")

    # use_fast=False matches the live pipeline's pinned preprocessing.
    processor = AutoProcessor.from_pretrained(base_model, trust_remote_code=True, use_fast=False)
    model = AutoVLM.from_pretrained(base_model, **kwargs)
    if adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, adapter)
    return model, processor
