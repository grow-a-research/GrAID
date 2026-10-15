# finetune/ — Qwen2.5-VL LoRA experiment (isolated)

This folder is **additive and isolated**. It does not import from, call, or
modify the live app, the OCR server, the database, or `requirements*.txt`.
Nothing here is wired into GrAId. Integrating a trained adapter is a separate,
deliberate step that happens only after you have tested the results yourself.

All git operations are yours; the root `.gitignore` is untouched and
`finetune/.gitignore` keeps handwriting, datasets and weights out of git.

## What it does

Fine-tunes the OCR model (`Qwen/Qwen2.5-VL-7B-Instruct`, the one the live
pipeline uses) with LoRA, then compares **base vs. base + adapter** on:

1. your 250 identification crops (`eval/out/crops` + `professor_sheet.csv`),
   scored by exact match against the teacher's accepted answers — read-only;
2. held-out public lines/words;
3. the held-out third of the consented samples (qualitative: few lines).

Training data: IAM lines (via Teklia/IAM-line) + IMGUR5K words + consented
short lines + synthetic augmentation + synthetic and real `[illegible]`
examples. Your local student crops are **never trained on**.

## Constraints (read these)

| Topic | Rule |
|---|---|
| Panelist/consented handwriting | usable, **never attributed**; neutral file names; folder is gitignored; a third is held out and never trained on |
| Labels | written by a human who can vouch for them; never from a model's reading; match the crop (crop out numbering marks and "!") |
| Licenses | IAM: non-commercial research, cite Marti & Bunke (IJDAR 2002) and say it came via the Teklia release; IMGUR5K: CC BY-NC 4.0, cite the repo/paper; do not redistribute images |
| Splits | Teklia's partitions are **not verified** equal to the official IAM split; don't call them that |
| Prompt | `prompts.LIVE_PROMPT` mirrors the live prompt (`check_prompt_sync.py`). `[illegible]` is only trained/evaluated under `ABSTAIN_PROMPT`, because the live prompt tells the model to always guess |
| Abstention | if the adapter is ever integrated with abstention, the app must handle the literal `[illegible]` text (route to review) — that is an integration decision, not part of this folder |
| Honesty | the result may be flat or negative on your crops; report it either way |

## Quick start (one command on the instance)

```bash
bash finetune/setup_vast.sh --smoke      # env check, IAM, IMGUR5K, consented, baseline, 20-step smoke test
bash finetune/setup_vast.sh --skip-imgur # fastest first pass: IAM + consented only
```

`setup_vast.sh` runs the steps below in order (it never reinstalls torch and
writes its log to `finetune/artifacts/setup.log`). Use the manual steps when
you want to control or repeat one stage.

## Run steps (fresh Vast.ai instance, RTX 5090 / CUDA 12.8+ template)

Run everything from the repo root so relative paths resolve. Copy these to
the instance: the `finetune/` folder, plus `eval/out/crops/` and
`eval/out/professor_sheet.csv` (the latter two only for the identification
test), plus `ocr_pipeline.py` only if you want the prompt-sync check.

```bash
# 0. GPU sanity (do NOT pip-install torch over the template's build)
python3 -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
nvidia-smi

# 1. dependencies
pip install -r finetune/requirements-finetune.txt

# 2. CPU checks
python finetune/selftest.py
python finetune/check_prompt_sync.py          # needs ocr_pipeline.py in the repo root

# 3. baseline on THIS hardware (base model, live prompt)
python finetune/eval_adapter.py --label base_live --prompt live \
    --id-crops-dir eval/out/crops --id-key-csv eval/out/professor_sheet.csv \
    --out finetune/artifacts/results/base_live.json

# 4. build the datasets
python finetune/build_iam.py --max-per-split 4000
#    IMGUR5K: download images with the official script first (see build_imgur5k.py),
#    then ALWAYS preview and look at the crops:
python finetune/build_imgur5k.py --images-dir <IMAGES_DIR> --annotations <imgur5k_annotations.json> --preview 20
python finetune/build_imgur5k.py --images-dir <IMAGES_DIR> --annotations <imgur5k_annotations.json> --max-words 30000
#    consented lines: put <name>.png + <name>.txt pairs in finetune/consented/ then
python finetune/build_consented.py --expect-upper

# 5. smoke test (a few steps, confirms memory + the whole loop)
python finetune/train_lora.py --out finetune/artifacts/smoke --max-steps 20 \
    --manifests finetune/data/manifest_iam.jsonl finetune/data/manifest_imgur5k.jsonl finetune/data/manifest_consented.jsonl

# 6. real run (the adapter is saved after every epoch)
python finetune/train_lora.py --out finetune/artifacts/run1 --epochs 2 \
    --manifests finetune/data/manifest_iam.jsonl finetune/data/manifest_imgur5k.jsonl finetune/data/manifest_consented.jsonl

# 7. evaluate the adapter under both prompts, then compare
python finetune/eval_adapter.py --label ad_live --prompt live --adapter finetune/artifacts/run1/epoch_2 \
    --id-crops-dir eval/out/crops --id-key-csv eval/out/professor_sheet.csv \
    --manifests finetune/data/manifest_iam.jsonl finetune/data/manifest_imgur5k.jsonl finetune/data/manifest_consented.jsonl \
    --split test --out finetune/artifacts/results/ad_live.json
python finetune/eval_adapter.py --label ad_abstain --prompt abstain --adapter finetune/artifacts/run1/epoch_2 \
    --id-crops-dir eval/out/crops --id-key-csv eval/out/professor_sheet.csv \
    --manifests finetune/data/manifest_iam.jsonl finetune/data/manifest_imgur5k.jsonl finetune/data/manifest_consented.jsonl \
    --split test --out finetune/artifacts/results/ad_abstain.json
python finetune/compare_runs.py finetune/artifacts/results/base_live.json finetune/artifacts/results/ad_live.json
```

For a fair table also run the base model with the same `--manifests ... --split test`
(label `base_live`, `--prompt live`) so the public/consented rows have a baseline.

**Before the lease ends (7-day cap):** copy `finetune/artifacts/` (adapters,
`results/`, `train_log.jsonl`) off the instance. A new instance starts empty.

## Reading the results

- **Identification accuracy** vs. the base on the same crops is the headline
  number (your earlier A5000 baseline was 72% on 50 answers; re-run it here).
- **False-abstain rate** on normal lines must stay near 0, otherwise the
  abstention examples made the model timid.
- **Output divergence** (compare_runs) is a regression guard for essay-style
  crops that have no ground truth — not an error rate.
- Report what is flat or worse as plainly as what improved.

## Files

| File | Purpose |
|---|---|
| `prompts.py`, `check_prompt_sync.py` | live prompt copy + abstain variant, and a drift check |
| `build_iam.py`, `build_imgur5k.py`, `build_consented.py` | datasets -> `data/manifest_*.jsonl` |
| `augment.py` | slant/blur/noise/shadow/JPEG and synthetic illegibility |
| `train_lora.py` | LoRA trainer (answer-token loss, adapter per epoch) |
| `eval_adapter.py`, `compare_runs.py` | standalone evaluation and diff |
| `selftest.py` | CPU-only checks |
