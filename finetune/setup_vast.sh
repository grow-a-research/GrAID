#!/usr/bin/env bash
# setup_vast.sh — environment + data (+ optional training and packaging) for the
# fine-tuning experiment, to be run by YOU on a Vast.ai instance, from the repo root.
#
#   bash finetune/setup_vast.sh --skip-imgur --smoke       # first pass: prove it all works
#   bash finetune/setup_vast.sh --train --package          # everything in one go
#
# Recommended for the one-go run (survives a dropped SSH session):
#   nohup bash finetune/setup_vast.sh --train --package > finetune/artifacts/nohup.out 2>&1 &
#   tail -f finetune/artifacts/setup.log
#
# Options:
#   --iam-max N        cap IAM lines per split (default 4000; 0 = all)
#   --imgur-max N      cap IMGUR5K word crops (default 30000; 0 = all)
#   --skip-imgur       don't download IMGUR5K at all
#   --skip-baseline    don't run the base-model baseline eval
#   --smoke            run a 20-step training smoke test
#   --train            full training run (see --epochs), then evaluate + compare
#   --epochs N         epochs for --train (default 2)
#   --package          bundle adapter + results + logs into ONE .tar.gz to download
#   --package-data     also bundle the built datasets (crops + manifests) so the next
#                      instance can skip the downloads. For YOUR private reuse only:
#                      IAM and IMGUR5K terms forbid redistributing them.
#
# Safe to re-run. Does NOT reinstall torch. Never uploads anything anywhere.
# Everything is written under finetune/ and ~/imgur5k_*.

set -euo pipefail

IAM_MAX=4000
IMGUR_MAX=30000
SKIP_IMGUR=0
SKIP_BASELINE=0
SMOKE=0
TRAIN=0
EPOCHS=2
PACKAGE=0
PACKAGE_DATA=0
while [ $# -gt 0 ]; do
  case "$1" in
    --iam-max)       IAM_MAX="$2"; shift 2 ;;
    --imgur-max)     IMGUR_MAX="$2"; shift 2 ;;
    --skip-imgur)    SKIP_IMGUR=1; shift ;;
    --skip-baseline) SKIP_BASELINE=1; shift ;;
    --smoke)         SMOKE=1; shift ;;
    --train)         TRAIN=1; shift ;;
    --epochs)        EPOCHS="$2"; shift 2 ;;
    --package)       PACKAGE=1; shift ;;
    --package-data)  PACKAGE_DATA=1; shift ;;
    -h|--help)       sed -n '2,32p' "$0"; exit 0 ;;
    *) echo "unknown option: $1"; exit 2 ;;
  esac
done

if [ ! -d finetune ] || [ ! -f finetune/train_lora.py ]; then
  echo "Run this from the repo root (the folder that contains finetune/)."; exit 2
fi
mkdir -p finetune/artifacts
exec > >(tee -a finetune/artifacts/setup.log) 2>&1

step() { echo; echo "=== $* ==="; }
IMGUR_REPO="$HOME/imgur5k_repo"
IMGUR_IMAGES="$HOME/imgur5k_images"

step "0. GPU check (torch is NOT reinstalled)"
python3 - <<'PY'
import sys
try:
    import torch
except Exception as e:
    print("torch is not importable:", e); sys.exit(1)
ok = torch.cuda.is_available()
print("torch", torch.__version__, "| cuda available:", ok)
if not ok:
    print("CUDA is not available. Pick a template with PyTorch built for CUDA 12.8+ "
          "(the RTX 5090 is Blackwell) and do not pip-install torch over it.")
    sys.exit(1)
p = torch.cuda.get_device_properties(0)
print(f"GPU: {p.name}, {p.total_memory/2**30:.1f} GiB")
PY

step "1. Python dependencies"
pip install -q -r finetune/requirements-finetune.txt

step "2. CPU self-test"
python3 finetune/selftest.py
if [ -f ocr_pipeline.py ]; then python3 finetune/check_prompt_sync.py || true; fi

step "3. IAM lines (Teklia/IAM-line on Hugging Face)"
if [ "$IAM_MAX" = "0" ]; then python3 finetune/build_iam.py
else python3 finetune/build_iam.py --max-per-split "$IAM_MAX"; fi

if [ "$SKIP_IMGUR" = "0" ]; then
  step "4. IMGUR5K (official repo + image download; slow, billed bandwidth)"
  if [ ! -d "$IMGUR_REPO" ]; then
    git clone --depth 1 https://github.com/facebookresearch/IMGUR5K-Handwriting-Dataset "$IMGUR_REPO"
  fi
  mkdir -p "$IMGUR_IMAGES"
  ( cd "$IMGUR_REPO" && python3 download_imgur5k.py --dataset_info_dir dataset_info --output_dir "$IMGUR_IMAGES" )
  ANN="$(find "$IMGUR_REPO" "$IMGUR_IMAGES" -name imgur5k_annotations.json 2>/dev/null | head -n 1 || true)"
  if [ -z "$ANN" ]; then
    echo "Could not find imgur5k_annotations.json after the download. Locate it and run:"
    echo "  python3 finetune/build_imgur5k.py --images-dir $IMGUR_IMAGES --annotations <path>"
  else
    echo "annotations: $ANN"
    python3 finetune/build_imgur5k.py --images-dir "$IMGUR_IMAGES" --annotations "$ANN" --preview 12
    echo ">>> Check finetune/artifacts/imgur5k_preview/: crops should be upright words."
    echo ">>> If they are tilted, rerun build_imgur5k.py with --angle-sign 1."
    if [ "$IMGUR_MAX" = "0" ]; then
      python3 finetune/build_imgur5k.py --images-dir "$IMGUR_IMAGES" --annotations "$ANN"
    else
      python3 finetune/build_imgur5k.py --images-dir "$IMGUR_IMAGES" --annotations "$ANN" --max-words "$IMGUR_MAX"
    fi
  fi
fi

step "5. Consented samples"
if [ -d finetune/consented ]; then
  python3 finetune/build_consented.py
else
  echo "finetune/consented/ not found — upload the crops + .txt files there, then run:"
  echo "  python3 finetune/build_consented.py"
fi

MANIFESTS=""
for m in finetune/data/manifest_iam.jsonl finetune/data/manifest_imgur5k.jsonl finetune/data/manifest_consented.jsonl; do
  [ -f "$m" ] && MANIFESTS="$MANIFESTS $m"
done
echo; echo "Manifests available:$MANIFESTS"

ID_ARGS=""
if [ -d eval/out/crops ] && [ -f eval/out/professor_sheet.csv ]; then
  ID_ARGS="--id-crops-dir eval/out/crops --id-key-csv eval/out/professor_sheet.csv"
else
  echo "(eval/out/crops or professor_sheet.csv not uploaded — evals skip identification)"
fi
RES=finetune/artifacts/results

if [ "$SKIP_BASELINE" = "0" ]; then
  step "6. Baseline: base model, live prompt (downloads ~16 GB of Qwen weights on first use)"
  # shellcheck disable=SC2086
  python3 finetune/eval_adapter.py --label base_live --prompt live $ID_ARGS \
      --manifests $MANIFESTS --split test --out "$RES/base_live.json"
fi

if [ "$SMOKE" = "1" ]; then
  step "7. Smoke test: 20 training steps"
  # shellcheck disable=SC2086
  python3 finetune/train_lora.py --out finetune/artifacts/smoke --max-steps 20 --manifests $MANIFESTS
fi

if [ "$TRAIN" = "1" ]; then
  step "8. Full training ($EPOCHS epochs; adapter saved after every epoch)"
  # shellcheck disable=SC2086
  python3 finetune/train_lora.py --out finetune/artifacts/run1 --epochs "$EPOCHS" --manifests $MANIFESTS
  ADAPTER="finetune/artifacts/run1/epoch_$EPOCHS"

  step "9. Evaluate the adapter under both prompts and compare"
  # shellcheck disable=SC2086
  python3 finetune/eval_adapter.py --label ad_live --prompt live --adapter "$ADAPTER" $ID_ARGS \
      --manifests $MANIFESTS --split test --out "$RES/ad_live.json"
  # shellcheck disable=SC2086
  python3 finetune/eval_adapter.py --label ad_abstain --prompt abstain --adapter "$ADAPTER" $ID_ARGS \
      --manifests $MANIFESTS --split test --out "$RES/ad_abstain.json"
  if [ -f "$RES/base_live.json" ]; then
    python3 finetune/compare_runs.py "$RES/base_live.json" "$RES/ad_live.json" | tee "$RES/compare_live.txt"
    python3 finetune/compare_runs.py "$RES/base_live.json" "$RES/ad_abstain.json" | tee "$RES/compare_abstain.txt"
  fi
fi

if [ "$PACKAGE" = "1" ] || [ "$PACKAGE_DATA" = "1" ]; then
  step "10. Package for transfer"
  STAMP="$(date +%Y%m%d_%H%M)"
  if [ "$PACKAGE" = "1" ]; then
    PATHS=""
    for p in artifacts/run1 artifacts/smoke artifacts/results artifacts/imgur5k_preview artifacts/setup.log; do
      [ -e "finetune/$p" ] && PATHS="$PATHS $p"
    done
    PKG="finetune/artifacts/results_package_$STAMP.tar.gz"
    # shellcheck disable=SC2086
    tar -czf "$PKG" -C finetune $PATHS
    echo "results package: $PKG ($(du -h "$PKG" | cut -f1))"
  fi
  if [ "$PACKAGE_DATA" = "1" ] && [ -d finetune/data ]; then
    DPKG="finetune/artifacts/data_bundle_$STAMP.tar.gz"
    tar -czf "$DPKG" -C finetune data
    echo "data bundle:     $DPKG ($(du -h "$DPKG" | cut -f1))"
    echo "  Restore on a new instance:  tar -xzf data_bundle_*.tar.gz -C finetune/"
  fi
  echo
  echo "Download to your laptop (run THERE; port and IP are on the Vast.ai 'Connect' panel):"
  echo "  scp -P <port> root@<ip>:$(pwd)/finetune/artifacts/results_package_*.tar.gz ."
  echo "Do this BEFORE stopping or destroying the instance."
fi

step "Done"
echo "If you changed settings, rerun just the stage you need; see finetune/README.md."
