"""
eval_adapter.py — evaluate the base model or base + adapter, standalone.

Loads the model itself (never calls the app or the OCR server) and mirrors the
live pipeline's decoding: left-padded batches, greedy, no_repeat_ngram_size=8,
confidence = minimum per-token probability along the answer.

Run the base model first for a like-for-like baseline on THIS hardware:

    python finetune/eval_adapter.py --label base_live --prompt live \
        --id-crops-dir eval/out/crops --id-key-csv eval/out/professor_sheet.csv \
        --manifests finetune/data/manifest_consented.jsonl --split test \
        --out finetune/artifacts/results/base_live.json

then the adapter under both prompts (add --adapter finetune/artifacts/run1/epoch_2,
--prompt live and --prompt abstain with different --label/--out), then:

    python finetune/compare_runs.py base_live.json adapter_live.json

Identification crops are only READ; nothing is written next to them. The
identification score mirrors identification_scoring (whitespace collapsed,
case ignored unless --case-sensitive, punctuation NOT normalized).
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

import torch
from PIL import Image
from tqdm import tqdm

from common import (DEFAULT_BASE_MODEL, FT_DIR, ILLEGIBLE, build_messages, cer, id_exact_match,
                    load_manifests, load_model_and_processor, wer)
from prompts import PROMPTS


def transcribe(model, processor, images: list[Image.Image], prompt: str,
               batch_size: int, max_new_tokens: int = 128) -> list[tuple[str, float]]:
    from qwen_vl_utils import process_vision_info

    tok = processor.tokenizer
    tok.padding_side = "left"
    stop_ids = {tok.pad_token_id, tok.eos_token_id} - {None}
    results: list[tuple[str, float]] = []
    model.eval()
    for i in range(0, len(images), batch_size):
        chunk = [im.convert("RGB") for im in images[i:i + batch_size]]
        msgs = [build_messages(im, prompt) for im in chunk]
        texts = [processor.apply_chat_template(m, tokenize=False, add_generation_prompt=True)
                 for m in msgs]
        image_inputs, video_inputs = process_vision_info(msgs)
        inputs = processor(text=texts, images=image_inputs, videos=video_inputs,
                           padding=True, return_tensors="pt")
        inputs = {k: v.to(model.device) for k, v in inputs.items() if hasattr(v, "to")}
        with torch.inference_mode():
            out = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False,
                                 no_repeat_ngram_size=8, output_scores=True,
                                 return_dict_in_generate=True)
        gen = out.sequences[:, inputs["input_ids"].shape[1]:]
        decoded = processor.batch_decode(gen, skip_special_tokens=True)
        probs = torch.stack(out.scores, dim=1).softmax(-1).gather(2, gen.unsqueeze(-1)).squeeze(-1)
        for row_ids, row_p, text in zip(gen.tolist(), probs, decoded):
            n = next((j for j, t in enumerate(row_ids) if t in stop_ids), len(row_ids))
            results.append((text.strip(), row_p[:n].min().item() if n > 0 else 1.0))
    return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--prompt", choices=sorted(PROMPTS), default="live")
    ap.add_argument("--base-model", default=DEFAULT_BASE_MODEL)
    ap.add_argument("--quant", default="bf16", choices=("bf16", "8bit", "4bit"))
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--manifests", nargs="*", default=[])
    ap.add_argument("--split", default="test")
    ap.add_argument("--max-per-source", type=int, default=300)
    ap.add_argument("--id-crops-dir", default=None)
    ap.add_argument("--id-key-csv", default=None)
    ap.add_argument("--case-sensitive", action="store_true")
    args = ap.parse_args()

    prompt = PROMPTS[args.prompt]
    model, processor = load_model_and_processor(args.base_model, args.quant, args.adapter)
    result: dict = {"label": args.label, "prompt_mode": args.prompt, "base_model": args.base_model,
                    "adapter": args.adapter, "quant": args.quant,
                    "case_sensitive": args.case_sensitive, "time": time.strftime("%Y-%m-%d %H:%M:%S")}

    # --- identification crops with the teacher's accepted answers -----------
    if args.id_crops_dir and args.id_key_csv:
        key_path = Path(args.id_key_csv)
        rows = list(csv.DictReader(key_path.open(encoding="utf-8-sig")))
        base = key_path.parent
        imgs, meta = [], []
        for r in rows:
            p = base / r["crop_image"]
            if p.exists():
                imgs.append(Image.open(p))
                meta.append(r)
        t0 = time.time()
        outs = transcribe(model, processor, imgs, prompt, args.batch_size)
        items = []
        for r, (text, conf) in zip(meta, outs):
            accepted = [a.strip() for a in r["accepted_answers"].split("|") if a.strip()]
            items.append({"item_id": r["item_id"], "expected": accepted, "got": text,
                          "confidence": round(conf, 4),
                          "correct": id_exact_match(accepted, text, args.case_sensitive)})
        n = len(items)
        result["identification"] = {
            "n": n,
            "accuracy": sum(i["correct"] for i in items) / max(1, n),
            "abstain_rate": sum(ILLEGIBLE in i["got"].casefold() for i in items) / max(1, n),
            "seconds_per_item": (time.time() - t0) / max(1, n),
            "items": items,
        }
        print(f"[{args.label}] identification: {result['identification']['accuracy']:.1%} of {n}")

    # --- manifest rows (held-out public data, consented test lines) ---------
    if args.manifests:
        rows = load_manifests(args.manifests, args.split)
        by_source: dict[str, list[dict]] = {}
        for r in rows:
            by_source.setdefault(r["source"], []).append(r)
        result["manifest"] = {}
        for src, rs in by_source.items():
            rs = rs[:args.max_per_source]
            imgs = [Image.open(FT_DIR / r["image"]) for r in rs]
            outs = transcribe(model, processor, imgs, prompt, args.batch_size)
            items, normal = [], []
            for r, (text, conf) in zip(rs, outs):
                it = {"id": r["id"], "kind": r.get("kind", "normal"), "expected": r["text"],
                      "got": text, "confidence": round(conf, 4)}
                items.append(it)
                if it["kind"] == "normal":
                    normal.append(it)
            illeg = [i for i in items if i["kind"] == "illegible"]
            n = max(1, len(normal))
            result["manifest"][src] = {
                "n": len(items),
                "cer": sum(cer(i["expected"], i["got"]) for i in normal) / n,
                "cer_ci": sum(cer(i["expected"], i["got"], True) for i in normal) / n,
                "wer": sum(wer(i["expected"], i["got"]) for i in normal) / n,
                "exact": sum(i["expected"] == i["got"] for i in normal) / n,
                "false_abstain_rate": sum(ILLEGIBLE in i["got"].casefold() for i in normal) / n,
                "illegible_n": len(illeg),
                "illegible_abstained": (sum(ILLEGIBLE in i["got"].casefold() for i in illeg)
                                        / len(illeg)) if illeg else None,
                "items": items,
            }
            m = result["manifest"][src]
            print(f"[{args.label}] {src}: n={m['n']} CER={m['cer']:.3f} WER={m['wer']:.3f} "
                  f"exact={m['exact']:.1%} false-abstain={m['false_abstain_rate']:.1%}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
