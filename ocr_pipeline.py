"""
OCR pipeline: model loading + inference helpers.

Imported by main.py (startup/endpoints) and by routers/api_v1.py
(DB-aware OCR endpoint) so the heavy model state lives here and
avoids circular imports.
"""
from __future__ import annotations

import base64
import io
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import cv2
import numpy as np
import requests
import torch
from PIL import Image, ImageDraw
from qwen_vl_utils import process_vision_info
from transformers import (
    AutoModelForVision2Seq,
    AutoProcessor,
    BitsAndBytesConfig,
)
from surya.detection import DetectionPredictor


QWEN_MODEL_ID = os.getenv("QWEN_MODEL_ID", "Qwen/Qwen2.5-VL-7B-Instruct")

# When set (e.g. to a rented GPU instance running vast_ocr_server.py), OCR is
# delegated to that remote server instead of loading Surya/Qwen locally. Use
# this when the local GPU lacks enough VRAM.
REMOTE_OCR_URL = os.getenv("REMOTE_OCR_URL", "").rstrip("/")


@dataclass
class Models:
    surya_detector: Any
    qwen_model: Any
    qwen_processor: Any


MODELS: Optional[Models] = None


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

def load_models(force_local: bool = False) -> None:
    """
    Load OCR models, or set up remote delegation.

    force_local=True is for vast_ocr_server.py, which IS the model host — it
    clears REMOTE_OCR_URL before calling this specifically so it always loads
    Surya/Qwen locally, regardless. Every other caller (the main app) leaves
    force_local=False: with no REMOTE_OCR_URL configured there, OCR just
    isn't available yet (MODELS stays None, endpoints 503) rather than
    silently loading the full model stack onto whatever local GPU happens to
    be present — that surprised more than it helped in practice.
    """
    global MODELS
    if MODELS is not None:
        return

    if REMOTE_OCR_URL:
        print(f"[Models] REMOTE_OCR_URL set — delegating OCR to {REMOTE_OCR_URL}")
        try:
            r = requests.get(f"{REMOTE_OCR_URL}/health", timeout=10)
            r.raise_for_status()
            print("[Models] Remote OCR server reachable.")
        except Exception as e:
            print(f"[Models] WARNING: could not reach remote OCR server yet: {e}")
        MODELS = Models(surya_detector=None, qwen_model=None, qwen_processor=None)
        return

    if not force_local:
        print(
            "[Models] No REMOTE_OCR_URL set — OCR endpoints will return 503 "
            "until one is configured and the server is restarted."
        )
        return

    print("[Models] Checking CUDA...")
    if not torch.cuda.is_available():
        raise RuntimeError(
            "CUDA not available. Install a CUDA-enabled PyTorch build and NVIDIA drivers."
        )
    print(f"[Models] CUDA OK — {torch.cuda.get_device_name(0)}")

    print("[Models] Loading Surya detection model...")
    surya_detector = DetectionPredictor()
    try:
        surya_detector.to("cuda")
        print("[Models] Surya loaded on CUDA.")
    except Exception:
        print("[Models] Surya CUDA move failed — running on CPU.")

    bnb_config = BitsAndBytesConfig(
        load_in_8bit=True,
    )

    print(f"[Models] Loading Qwen processor ({QWEN_MODEL_ID})...")
    # Pinned to the "slow" (pure-PIL) image processor on purpose: transformers
    # now defaults new loads to a different "fast" implementation that the
    # library itself warns can produce slightly different preprocessed pixels
    # for the same input image. Pinning keeps this pipeline's preprocessing
    # stable across transformers upgrades instead of silently drifting.
    qwen_processor = AutoProcessor.from_pretrained(
        QWEN_MODEL_ID, trust_remote_code=True, use_fast=False,
    )

    print("[Models] Loading Qwen model in 8-bit (this may take several minutes)...")
    # Pinned to a single GPU on purpose: this 7B model only needs ~8-10GB in
    # 8-bit, which fits on one card with room to spare. device_map="auto"
    # would split it across all visible GPUs, adding PCIe cross-GPU transfer
    # overhead on every forward pass for no VRAM benefit on a rig like this.
    qwen_model = AutoModelForVision2Seq.from_pretrained(
        QWEN_MODEL_ID,
        quantization_config=bnb_config,
        device_map={"": 0},
        torch_dtype=torch.float16,
        trust_remote_code=True,
    )
    qwen_model.eval()
    print("[Models] Qwen loaded and ready.")

    MODELS = Models(
        surya_detector=surya_detector,
        qwen_model=qwen_model,
        qwen_processor=qwen_processor,
    )
    print("[Models] All models ready.")


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def _pil_to_cv2_bgr(img: Image.Image) -> np.ndarray:
    rgb = np.array(img.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def preprocess_for_detection(img: Image.Image) -> Image.Image:
    """Grayscale → denoise → adaptive threshold → PIL RGB (Surya expects PIL)."""
    bgr = _pil_to_cv2_bgr(img)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    den = cv2.fastNlMeansDenoising(gray, None, h=12, templateWindowSize=7, searchWindowSize=21)
    thr = cv2.adaptiveThreshold(
        den, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
    )
    rgb = cv2.cvtColor(thr, cv2.COLOR_GRAY2RGB)
    return Image.fromarray(rgb)


def draw_boxes(image: Image.Image, boxes_xyxy: list[tuple[int, int, int, int]]) -> Image.Image:
    out = image.convert("RGB").copy()
    draw = ImageDraw.Draw(out)
    for (x1, y1, x2, y2) in boxes_xyxy:
        draw.rectangle([x1, y1, x2, y2], outline=(255, 0, 0), width=2)
    return out


def encode_png_base64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _extract_surya_xyxy(pred: Any) -> list[tuple[int, int, int, int]]:
    boxes: list[tuple[int, int, int, int]] = []
    if pred is None:
        return boxes
    bboxes = getattr(pred, "bboxes", None)
    if not bboxes:
        return boxes
    for b in bboxes:
        rect = getattr(b, "bbox", None)
        if not rect or len(rect) != 4:
            continue
        x1, y1, x2, y2 = rect
        boxes.append((int(x1), int(y1), int(x2), int(y2)))
    return boxes


def _vertical_overlap_ratio(
    a: tuple[int, int, int, int], b: tuple[int, int, int, int]
) -> float:
    _, ay1, _, ay2 = a
    _, by1, _, by2 = b
    inter = min(ay2, by2) - max(ay1, by1)
    if inter <= 0:
        return 0.0
    return inter / min(ay2 - ay1, by2 - by1)


def merge_overlapping_boxes(
    boxes: list[tuple[int, int, int, int]], overlap_thresh: float = 0.7
) -> list[tuple[int, int, int, int]]:
    """Merge line boxes whose vertical extents overlap significantly.

    Surya occasionally emits multiple overlapping/partial detections for
    the same physical line (denser handwriting, tight line spacing), which
    then get OCR'd separately by Qwen as duplicate, partial reads of the
    same text — each one incomplete, so the model fills gaps with guesses.
    Merging them into a single full-width crop before OCR fixes this at
    the source instead of downstream.

    Threshold is intentionally high (0.7, not just >0): two genuine
    duplicate detections of the same line overlap nearly completely, while
    two distinct but tightly-spaced lines can still show partial vertical
    overlap just from ascenders/descenders bleeding into the neighboring
    line's box. A low threshold conflates the two and fuses real, separate
    lines into one oversized multi-line crop.
    """
    merged = list(boxes)
    changed = True
    while changed:
        changed = False
        merged.sort(key=lambda b: b[1])
        next_merged: list[tuple[int, int, int, int]] = []
        for box in merged:
            for i, m in enumerate(next_merged):
                if _vertical_overlap_ratio(box, m) > overlap_thresh:
                    unioned = (
                        min(m[0], box[0]), min(m[1], box[1]),
                        max(m[2], box[2]), max(m[3], box[3]),
                    )
                    if unioned != m:
                        changed = True
                    next_merged[i] = unioned
                    break
            else:
                next_merged.append(box)
        merged = next_merged
    return merged


def _has_ink(
    original_rgb: Image.Image,
    box: tuple[int, int, int, int],
    min_ink_ratio: float = 0.005,
    min_row_spread: float = 0.2,
) -> bool:
    """Reject boxes over blank/near-blank regions (paper texture, faint
    ruled lines, scan noise) before they reach Qwen. A crop with no real
    content gives the model nothing to transcribe, so instead of
    returning empty it hallucinates plausible-looking filler text.

    A printed ruled line spans nearly the full crop width but only 1-3
    pixel rows, so it can still pass a plain mean-darkness check (a thin
    line across a wide crop adds up). Real handwriting has ink spread
    across a meaningful fraction of the crop's height (ascenders,
    x-height, descenders) — so require that shape too, not just a
    darkness total.
    """
    w, h = original_rgb.size
    x1, y1, x2, y2 = box
    x1c, y1c = max(0, x1), max(0, y1)
    x2c, y2c = min(w, x2), min(h, y2)
    if x2c <= x1c or y2c <= y1c:
        return False
    crop = np.array(original_rgb.convert("L").crop((x1c, y1c, x2c, y2c)))
    if crop.size == 0:
        return False
    dark_mask = crop < 180
    dark_ratio = float(dark_mask.mean())
    row_ink_ratio = dark_mask.mean(axis=1)
    ink_rows = int((row_ink_ratio > 0.02).sum())
    row_spread = ink_rows / crop.shape[0]
    keep = dark_ratio >= min_ink_ratio and row_spread >= min_row_spread
    print(
        f"[InkFilter] box={box} dark_ratio={dark_ratio:.4f} "
        f"row_spread={row_spread:.4f} keep={keep}"
    )
    return keep


def crop_lines(
    original_rgb: Image.Image, boxes_xyxy: list[tuple[int, int, int, int]]
) -> list[Image.Image]:
    w, h = original_rgb.size
    crops: list[Image.Image] = []
    for (x1, y1, x2, y2) in boxes_xyxy:
        x1c, y1c = max(0, x1), max(0, y1)
        x2c, y2c = min(w, x2), min(h, y2)
        if x2c <= x1c or y2c <= y1c:
            continue
        crops.append(original_rgb.crop((x1c, y1c, x2c, y2c)))
    return crops


# ---------------------------------------------------------------------------
# Qwen inference
# ---------------------------------------------------------------------------

# How many line-crops go through generate() together. Bigger batches use the
# GPU more efficiently (one forward pass instead of many) but cost more VRAM;
# 8 is comfortable headroom on a 16GB card for this model. Override with
# QWEN_OCR_BATCH_SIZE if a page has unusually many/large line crops.
_OCR_BATCH_SIZE = int(os.getenv("QWEN_OCR_BATCH_SIZE", "8"))

# Token budget for a genuine single line of handwriting, and a hard ceiling
# so one abnormally tall crop can't blow up generation time. A crop taller
# than one line (e.g. a merge_overlapping_boxes box that still spans more
# than one physical line) gets a multiple of this instead — see
# run_ocr_pipeline's per-crop budget calculation.
_LINE_TOKENS = 128
_MAX_LINE_TOKENS = 640


def qwen_ocr_lines(
    line_images: list[Image.Image],
    token_budgets: list[int] | None = None,
) -> list[tuple[str, float]]:
    """
    Returns (transcribed_text, confidence) per line. Confidence is the
    minimum per-token generation probability Qwen assigned along the line —
    its own least-certain moment — distinct from ocr_clarity (pre-OCR image
    blur) and from the grader's later self-reported confidence.

    token_budgets, when given, is a list parallel to line_images estimating
    how many tokens each crop actually needs (a crop covering more than one
    physical line needs more room than a single line does). generate() sets
    one max_new_tokens per batch, so each batch uses the largest budget among
    its own crops — shorter crops in the same batch simply stop early at
    their own EOS token, so this costs nothing for them.
    """
    assert MODELS is not None
    if not line_images:
        return []
    if token_budgets is None:
        token_budgets = [_LINE_TOKENS] * len(line_images)

    prompt = (
        "Transcribe EXACTLY what is written in this image line, character-for-character. "
        "This is a handwriting recognition task, not a writing-correction task — report "
        "the ink on the page even when it is grammatically wrong. "
        "Preserve all spelling errors, capitalization, and punctuation exactly as written. "
        "Do NOT correct grammar or spelling. Do NOT add or drop a letter just because it "
        "would be the grammatically expected form — for example, if the handwriting reads "
        "\"solve problem\" (singular, no trailing 's'), transcribe it as \"solve problem\", "
        "even though \"solve problems\" reads more naturally. Visual evidence always wins "
        "over what sounds correct. Do not add, remove, or rephrase any words. "
        "If a word is illegible, transcribe your best visual guess of the actual letters — "
        "do not substitute a different, more common real word. Output only the transcribed "
        "text, nothing else."
    )

    # Left-padding is required for batched causal-LM generation: with
    # right-padding each sequence's real last token would sit at a different
    # column, so the model would start generating from padding instead of
    # from the end of the actual prompt.
    tokenizer = MODELS.qwen_processor.tokenizer
    if tokenizer.padding_side != "left":
        tokenizer.padding_side = "left"
    # Positions from the first EOS/pad token onward are generation padding,
    # not real transcription — excluded when reducing to a line confidence.
    stop_ids = {tokenizer.pad_token_id, tokenizer.eos_token_id} - {None}

    texts: list[tuple[str, float]] = []
    for start in range(0, len(line_images), _OCR_BATCH_SIZE):
        batch_images = line_images[start:start + _OCR_BATCH_SIZE]
        batch_max_tokens = min(
            _MAX_LINE_TOKENS,
            max(token_budgets[start:start + _OCR_BATCH_SIZE]),
        )
        batch_messages = [
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": img},
                        {"type": "text", "text": prompt},
                    ],
                }
            ]
            for img in batch_images
        ]
        batch_texts = [
            MODELS.qwen_processor.apply_chat_template(
                msgs, tokenize=False, add_generation_prompt=True
            )
            for msgs in batch_messages
        ]
        image_inputs, video_inputs = process_vision_info(batch_messages)
        inputs = MODELS.qwen_processor(
            text=batch_texts,
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        )
        inputs = {k: v.to(MODELS.qwen_model.device) for k, v in inputs.items() if hasattr(v, "to")}

        with torch.inference_mode():
            outputs = MODELS.qwen_model.generate(
                **inputs,
                max_new_tokens=batch_max_tokens,
                do_sample=False,
                output_scores=True,
                return_dict_in_generate=True,
            )

        # Left-padding keeps every sequence's prompt the same length, so one
        # slice index correctly strips the prompt off all rows in the batch.
        prompt_len = inputs["input_ids"].shape[1]
        gen_only = outputs.sequences[:, prompt_len:]
        decoded = MODELS.qwen_processor.batch_decode(gen_only, skip_special_tokens=True)

        # outputs.scores[t] = pre-softmax logits for generation step t, shape
        # (batch, vocab) — gather the probability the model actually assigned
        # to the token it went with at each step.
        step_probs = torch.stack(outputs.scores, dim=1).softmax(dim=-1)
        token_probs = step_probs.gather(2, gen_only.unsqueeze(-1)).squeeze(-1)

        for row_ids, row_probs, text in zip(gen_only.tolist(), token_probs, decoded):
            real_len = next((i for i, tid in enumerate(row_ids) if tid in stop_ids), len(row_ids))
            confidence = row_probs[:real_len].min().item() if real_len > 0 else 1.0
            texts.append((text.strip(), confidence))

    return texts


# ---------------------------------------------------------------------------
# High-level pipeline entry point
# ---------------------------------------------------------------------------

def run_ocr_pipeline(
    original: Image.Image,
    include_boxed_image: bool = True,
) -> tuple[str, list[tuple[int, int, int, int]], Image.Image, bool]:
    """
    Run the full OCR pipeline on a single PIL image.

    include_boxed_image controls whether the remote path (see
    _run_remote_ocr_pipeline) bothers building/transmitting the annotated
    debug image over the network — every grading call site discards it
    (`_`), so for those it's pure wasted encode time + payload size. Only
    the standalone OCR Tool debug page (main.py's /extract) actually
    displays it, so that's the only caller that needs the default True.

    Returns:
        full_text      – lines joined by newline, unmodified (nothing is
                          ever dropped based on confidence — see
                          low_confidence below)
        boxes           – list of (x1,y1,x2,y2) tuples, top-to-bottom order
        boxed_image     – original image with red bounding boxes drawn (or,
                          when include_boxed_image=False on the remote path,
                          just the original image — callers that need the
                          real annotated image must pass include_boxed_image=True)
        low_confidence  – True if any line came back below
                          OCR_MIN_LINE_CONFIDENCE (a likely hallucination on
                          blank/erased ink, or just genuinely hard-to-read
                          handwriting) — callers should flag the answer for
                          human review rather than act on this themselves.
    """
    assert MODELS is not None

    if REMOTE_OCR_URL:
        return _run_remote_ocr_pipeline(original, include_boxed_image)

    if os.getenv("SURYA_RAW_DETECT") == "1":
        det_img = original.convert("RGB")
    else:
        det_img = preprocess_for_detection(original)

    t_surya = time.perf_counter()
    preds = MODELS.surya_detector([det_img])
    print(f"[Timing] Surya line-detection took {time.perf_counter() - t_surya:.2f}s")

    pred0 = preds[0] if preds else None
    boxes = _extract_surya_xyxy(pred0)
    boxes = merge_overlapping_boxes(boxes)
    boxes_sorted = sorted(boxes, key=lambda b: (b[1], b[0]))
    boxes_sorted = [b for b in boxes_sorted if _has_ink(original, b)]

    boxed = draw_boxes(original, boxes_sorted)

    if not boxes_sorted:
        return "", [], boxed, False

    line_crops = crop_lines(original, boxes_sorted)

    # Estimate token budget per crop from its height relative to a typical
    # single line on this page. A merge_overlapping_boxes box that still
    # ended up spanning several physical lines (tight/uneven spacing) would
    # otherwise get the same fixed budget as a real single line and cut off
    # mid-sentence. Median height is used as the single-line reference
    # instead of the smallest box, since the smallest box on a page is often
    # a short partial line (e.g. "Name:") rather than a representative one.
    heights = sorted(b[3] - b[1] for b in boxes_sorted)
    ref_height = max(heights[len(heights) // 2], 1)
    token_budgets = [
        min(_MAX_LINE_TOKENS, _LINE_TOKENS * max(1, round((b[3] - b[1]) / ref_height)))
        for b in boxes_sorted
    ]

    t_qwen = time.perf_counter()
    line_results = qwen_ocr_lines(line_crops, token_budgets)
    print(
        f"[Timing] Qwen transcription of {len(line_crops)} line(s) took "
        f"{time.perf_counter() - t_qwen:.2f}s"
    )
    # A crop with real ink but no actual legible content (e.g. an erased/
    # scratched-out note that still leaves a visible smudge) still passes
    # _has_ink() — it has ink — but the transcription prompt forces Qwen to
    # guess at it anyway rather than return nothing. That guess should come
    # out with a low confidence score even when the rest of the page reads
    # confidently. Text is never dropped/altered here, though — a single
    # low-probability token can drag a whole line's score down even when
    # only one word in that line is actually bad (confidence is a per-LINE
    # minimum, not per-word), so auto-deleting on this signal risks losing
    # real student content along with genuine hallucinations. Instead this
    # only flags the answer for human review upstream (see callers) —
    # full_text always contains everything Qwen produced, unmodified.
    #
    # 0.15 is based on one observed real example (submission #11): a
    # hallucinated line scored 0.095 while every genuine line on the same
    # page scored 0.282-0.596 — a clear gap. Biased toward the low end of
    # that gap on purpose: flagging too eagerly just means more submissions
    # for a human to double-check; the failure mode to avoid is silence.
    _MIN_LINE_CONFIDENCE = float(os.getenv("OCR_MIN_LINE_CONFIDENCE", "0.15"))

    clean_lines: list[str] = []
    low_confidence = False
    for text, conf in line_results:
        if not text or not text.strip():
            continue
        # Log every line's own confidence (not just the aggregate) so a
        # specific bad line — like a hallucinated word — can be identified
        # directly from the log instead of guessed at from min/mean.
        print(f"[OCR confidence] {conf:.3f} — {text[:80]!r}")
        if conf < _MIN_LINE_CONFIDENCE:
            print(f"[OCR confidence] below threshold {_MIN_LINE_CONFIDENCE} — flagging for review")
            low_confidence = True
        clean_lines.append(" ".join(text.split()))

    full_text = "\n".join(clean_lines).strip()

    confidences = [c for t, c in line_results if t and t.strip()]
    if confidences:
        low = sum(1 for c in confidences if c < 0.5)
        print(
            f"[OCR confidence] page summary: min={min(confidences):.2f} "
            f"mean={sum(confidences) / len(confidences):.2f} "
            f"({low}/{len(confidences)} line(s) below 0.50)"
        )

    return full_text, boxes_sorted, boxed, low_confidence


def _run_remote_ocr_pipeline(
    original: Image.Image,
    include_boxed_image: bool = True,
) -> tuple[str, list[tuple[int, int, int, int]], Image.Image, bool]:
    """Send the image to the remote OCR server and adapt its response
    to the same (full_text, boxes, boxed_image, low_confidence) shape as
    the local pipeline."""
    buf = io.BytesIO()
    original.convert("RGB").save(buf, format="PNG")
    buf.seek(0)

    resp = requests.post(
        f"{REMOTE_OCR_URL}/ocr",
        files={"file": ("image.png", buf, "image/png")},
        params={"include_boxed_image": include_boxed_image},
        timeout=180,
    )
    resp.raise_for_status()
    data = resp.json()

    boxes = [tuple(b) for b in data.get("boxes", [])]
    boxed_b64 = data.get("boxed_image_png_base64") or ""
    if boxed_b64:
        boxed = Image.open(io.BytesIO(base64.b64decode(boxed_b64))).convert("RGB")
    else:
        # Server skipped building/encoding it (include_boxed_image=False) —
        # callers that discard this value (all grading call sites) don't
        # care what's here; only main.py's /extract debug endpoint needs
        # the real annotated image, and it always passes True.
        boxed = original

    return data.get("text", ""), boxes, boxed, bool(data.get("low_confidence", False))
