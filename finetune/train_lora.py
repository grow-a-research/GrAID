"""
train_lora.py — LoRA fine-tune of Qwen2.5-VL on handwriting line/word crops.

Standalone: loads the base model itself, never touches the live OCR server or
app code. Writes an adapter directory per epoch under --out (a few hundred MB
at most). The base weights are not modified.

    python finetune/train_lora.py \
        --manifests finetune/data/manifest_iam.jsonl \
                    finetune/data/manifest_imgur5k.jsonl \
                    finetune/data/manifest_consented.jsonl \
        --out finetune/artifacts/run1 --epochs 2

Training details that matter:
  * Same chat format and (with prob. 1 - abstain_prompt_fraction) the same
    prompt as the live pipeline, so the adapter sees what inference sends.
  * Loss is computed on the answer tokens only.
  * Only the language-model linear layers get LoRA by default (--tune-vision
    also adapts the vision tower).
  * Consented rows are repeated (--consented-repeat) because there are few;
    augmentation makes each repeat different. Their held-out `test` split is
    never used here.
  * With prob. --illegible-fraction a clean sample is destroyed and relabeled
    "[illegible]" (always under the abstain prompt).
"""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from pathlib import Path

import torch
from PIL import Image
from tqdm import tqdm

from augment import augment, make_illegible
from common import (DEFAULT_BASE_MODEL, FT_DIR, ILLEGIBLE, build_messages,
                    load_manifests, load_model_and_processor)
from prompts import ABSTAIN_PROMPT, LIVE_PROMPT


def lora_target_names(model, tune_vision: bool) -> list[str]:
    suffixes = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
    if tune_vision:
        suffixes.append("qkv")
    names = []
    for name, mod in model.named_modules():
        if isinstance(mod, torch.nn.Linear) and name.endswith(tuple(suffixes)):
            if not tune_vision and ("visual" in name or "vision" in name):
                continue
            names.append(name)
    return names


def make_batch(rows, processor, rng, args, device, train: bool):
    from qwen_vl_utils import process_vision_info

    images, prompts, answers = [], [], []
    for row in rows:
        img = Image.open(FT_DIR / row["image"]).convert("RGB")
        text, kind = row["text"], row.get("kind", "normal")
        if train and kind != "illegible" and rng.random() < args.illegible_fraction:
            img, text, kind = make_illegible(img, rng), ILLEGIBLE, "illegible"
        elif train and rng.random() < args.augment_prob:
            img = augment(img, rng)
        use_abstain = kind == "illegible" or rng.random() < args.abstain_prompt_fraction
        images.append(img)
        prompts.append(ABSTAIN_PROMPT if use_abstain else LIVE_PROMPT)
        answers.append(text)

    msgs = [build_messages(im, p) for im, p in zip(images, prompts)]
    prompt_texts = [processor.apply_chat_template(m, tokenize=False, add_generation_prompt=True)
                    for m in msgs]
    full_texts = [t + a + "<|im_end|>" for t, a in zip(prompt_texts, answers)]
    image_inputs, video_inputs = process_vision_info(msgs)

    tok = processor.tokenizer
    tok.padding_side = "right"
    enc = processor(text=full_texts, images=image_inputs, videos=video_inputs,
                    padding=True, return_tensors="pt")

    labels = torch.full_like(enc["input_ids"], -100)
    for i, ans in enumerate(answers):
        n = len(tok(ans + "<|im_end|>", add_special_tokens=False)["input_ids"])
        length = int(enc["attention_mask"][i].sum())
        labels[i, length - n:length] = enc["input_ids"][i, length - n:length]

    batch = {k: v.to(device) for k, v in enc.items() if hasattr(v, "to")}
    batch["labels"] = labels.to(device)
    return batch


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifests", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base-model", default=DEFAULT_BASE_MODEL)
    ap.add_argument("--quant", default="bf16", choices=("bf16", "8bit", "4bit"))
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--grad-accum", type=int, default=4)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--lora-dropout", type=float, default=0.05)
    ap.add_argument("--tune-vision", action="store_true")
    ap.add_argument("--init-adapter", default=None,
                    help="path to a saved adapter directory to continue training from")
    ap.add_argument("--max-train-per-source", type=int, default=0, help="0 = all")
    ap.add_argument("--consented-repeat", type=int, default=8)
    ap.add_argument("--augment-prob", type=float, default=0.7)
    ap.add_argument("--illegible-fraction", type=float, default=0.05)
    ap.add_argument("--abstain-prompt-fraction", type=float, default=0.5)
    ap.add_argument("--val-max", type=int, default=300)
    ap.add_argument("--max-steps", type=int, default=0, help="stop early (smoke test)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    from peft import LoraConfig, get_peft_model

    rng = random.Random(args.seed)
    torch.manual_seed(args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    train_rows = load_manifests(args.manifests, "train")
    val_rows = [r for r in load_manifests(args.manifests, "val") if r["source"] != "consented"]
    by_source: dict[str, list[dict]] = {}
    for r in train_rows:
        by_source.setdefault(r["source"], []).append(r)
    pool: list[dict] = []
    for src, rows in by_source.items():
        if args.max_train_per_source and len(rows) > args.max_train_per_source:
            rows = rng.sample(rows, args.max_train_per_source)
        pool.extend(rows * (args.consented_repeat if src == "consented" else 1))
    if not pool:
        raise SystemExit("No training rows. Build the manifests first (see README).")
    rng.shuffle(val_rows)
    val_rows = val_rows[:args.val_max]
    print(f"Train pool: {len(pool)} samples "
          f"({ {s: len(v) for s, v in by_source.items()} }), val: {len(val_rows)}")

    model, processor = load_model_and_processor(args.base_model, args.quant)
    device = next(model.parameters()).device
    model.config.use_cache = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()

    if args.init_adapter:
        # Continue training from a saved adapter (e.g. after a lost instance).
        # Optimizer state is not saved, so this restarts the schedule.
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, args.init_adapter, is_trainable=True)
        print(f"Continuing from adapter {args.init_adapter}")
    else:
        targets = lora_target_names(model, args.tune_vision)
        print(f"LoRA on {len(targets)} linear layers (r={args.lora_r}, alpha={args.lora_alpha})")
        model = get_peft_model(model, LoraConfig(
            r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=args.lora_dropout,
            target_modules=targets, bias="none", task_type="CAUSAL_LM"))
    model.print_trainable_parameters()

    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=args.lr, weight_decay=0.0)
    steps_per_epoch = math.ceil(len(pool) / (args.batch_size * args.grad_accum))
    total_steps = steps_per_epoch * args.epochs
    if args.max_steps:
        total_steps = min(total_steps, args.max_steps)
    warmup = max(1, int(0.03 * total_steps))
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, (s + 1) / warmup) * 0.5 * (1 + math.cos(math.pi * min(1.0, s / total_steps))))

    (out / "run_config.json").write_text(json.dumps(vars(args), indent=2), encoding="utf-8")
    log = (out / "train_log.jsonl").open("a", encoding="utf-8")

    def evaluate() -> float:
        model.eval()
        total, n = 0.0, 0
        with torch.no_grad():
            for i in range(0, len(val_rows), args.batch_size):
                b = make_batch(val_rows[i:i + args.batch_size], processor, random.Random(0),
                               args, device, train=False)
                with torch.autocast("cuda", dtype=torch.bfloat16):
                    total += model(**b).loss.item() * len(val_rows[i:i + args.batch_size])
                n += len(val_rows[i:i + args.batch_size])
        model.train()
        return total / max(1, n)

    model.train()
    step, t0, done = 0, time.time(), False
    for epoch in range(1, args.epochs + 1):
        order = pool[:]
        rng.shuffle(order)
        micro = [order[i:i + args.batch_size] for i in range(0, len(order), args.batch_size)]
        run_loss, run_n = 0.0, 0
        for mi, rows in enumerate(tqdm(micro, desc=f"epoch {epoch}")):
            batch = make_batch(rows, processor, rng, args, device, train=True)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                loss = model(**batch).loss
            (loss / args.grad_accum).backward()
            run_loss += loss.item()
            run_n += 1
            if (mi + 1) % args.grad_accum == 0 or mi == len(micro) - 1:
                torch.nn.utils.clip_grad_norm_(params, 1.0)
                opt.step()
                sched.step()
                opt.zero_grad(set_to_none=True)
                step += 1
                if step % 10 == 0:
                    rec = {"step": step, "epoch": epoch, "loss": run_loss / run_n,
                           "lr": sched.get_last_lr()[0], "elapsed_s": round(time.time() - t0)}
                    log.write(json.dumps(rec) + "\n"); log.flush()
                    run_loss, run_n = 0.0, 0
                if args.max_steps and step >= args.max_steps:
                    done = True
                    break
        val_loss = evaluate() if val_rows else float("nan")
        ckpt = out / f"epoch_{epoch}"
        model.save_pretrained(ckpt)
        rec = {"epoch": epoch, "step": step, "val_loss": val_loss, "adapter": str(ckpt)}
        log.write(json.dumps(rec) + "\n"); log.flush()
        print(f"epoch {epoch}: val_loss={val_loss:.4f}  saved {ckpt}")
        if done:
            break
    print(f"Done in {round(time.time() - t0)}s. Copy {out} off the instance before the lease ends.")


if __name__ == "__main__":
    main()
