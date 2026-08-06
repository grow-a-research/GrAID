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

def load_models() -> None:
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
    qwen_processor = AutoProcessor.from_pretrained(QWEN_MODEL_ID, trust_remote_code=True)

    print("[Models] Loading Qwen model in 8-bit (this may take several minutes)...")
    qwen_model = AutoModelForVision2Seq.from_pretrained(
        QWEN_MODEL_ID,
        quantization_config=bnb_config,
        device_map="auto",
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
    boxes: list[tuple[int, int, int, int]], overlap_thresh: float = 0.5
) -> list[tuple[int, int, int, int]]:
    """Merge line boxes whose vertical extents overlap significantly.

    Surya occasionally emits multiple overlapping/partial detections for
    the same physical line (denser handwriting, tight line spacing), which
    then get OCR'd separately by Qwen as duplicate, partial reads of the
    same text — each one incomplete, so the model fills gaps with guesses.
    Merging them into a single full-width crop before OCR fixes this at
    the source instead of downstream.
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

def qwen_ocr_lines(line_images: list[Image.Image]) -> list[str]:
    assert MODELS is not None
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
    texts: list[str] = []
    for img in line_images:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": img},
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        text = MODELS.qwen_processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = MODELS.qwen_processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            return_tensors="pt",
        )
        inputs = {k: v.to(MODELS.qwen_model.device) for k, v in inputs.items() if hasattr(v, "to")}

        with torch.inference_mode():
            output_ids = MODELS.qwen_model.generate(
                **inputs,
                max_new_tokens=128,
                do_sample=False,
            )

        prompt_len = inputs["input_ids"].shape[1]
        gen_only = output_ids[:, prompt_len:]
        decoded = MODELS.qwen_processor.batch_decode(gen_only, skip_special_tokens=True)
        texts.append(decoded[0].strip())
    return texts


# ---------------------------------------------------------------------------
# High-level pipeline entry point
# ---------------------------------------------------------------------------

def run_ocr_pipeline(
    original: Image.Image,
) -> tuple[str, list[tuple[int, int, int, int]], Image.Image]:
    """
    Run the full OCR pipeline on a single PIL image.

    Returns:
        full_text   – lines joined by newline
        boxes       – list of (x1,y1,x2,y2) tuples, top-to-bottom order
        boxed_image – original image with red bounding boxes drawn
    """
    assert MODELS is not None

    if REMOTE_OCR_URL:
        return _run_remote_ocr_pipeline(original)

    if os.getenv("SURYA_RAW_DETECT") == "1":
        det_img = original.convert("RGB")
    else:
        det_img = preprocess_for_detection(original)
    preds = MODELS.surya_detector([det_img])
    pred0 = preds[0] if preds else None
    boxes = _extract_surya_xyxy(pred0)
    boxes = merge_overlapping_boxes(boxes)
    boxes_sorted = sorted(boxes, key=lambda b: (b[1], b[0]))
    boxes_sorted = [b for b in boxes_sorted if _has_ink(original, b)]

    boxed = draw_boxes(original, boxes_sorted)

    if not boxes_sorted:
        return "", [], boxed

    line_crops = crop_lines(original, boxes_sorted)
    line_texts = qwen_ocr_lines(line_crops)
    clean_lines = [" ".join(t.split()) for t in line_texts if t and t.strip()]
    full_text = "\n".join(clean_lines).strip()

    return full_text, boxes_sorted, boxed


def _run_remote_ocr_pipeline(
    original: Image.Image,
) -> tuple[str, list[tuple[int, int, int, int]], Image.Image]:
    """Send the image to the remote OCR server and adapt its response
    to the same (full_text, boxes, boxed_image) shape as the local pipeline."""
    buf = io.BytesIO()
    original.convert("RGB").save(buf, format="PNG")
    buf.seek(0)

    resp = requests.post(
        f"{REMOTE_OCR_URL}/ocr",
        files={"file": ("image.png", buf, "image/png")},
        timeout=180,
    )
    resp.raise_for_status()
    data = resp.json()

    boxes = [tuple(b) for b in data.get("boxes", [])]
    boxed_bytes = base64.b64decode(data["boxed_image_png_base64"])
    boxed = Image.open(io.BytesIO(boxed_bytes)).convert("RGB")

    return data.get("text", ""), boxes, boxed
