"""
trocr_ocr.py — experimental TrOCR transcription path (GPU host only).

A specialised handwriting model (default microsoft/trocr-large-handwritten,
~1.4GB) run per detected line, for comparison against the Qwen2.5-VL path.
Serves the /ocr_trocr endpoint in vast_ocr_server.py.

Deliberately additive: this module *calls into* ocr_pipeline for line
detection and cropping and never modifies it, so /ocr, /ocr_id and every
stored transcription produced by them are unaffected. Nothing in the app
uses this path — it exists to be benchmarked.

Why it might beat the VLM here: TrOCR is an encoder-decoder trained to
transcribe handwriting line images, so it has no chat-style prior to fall
back on when a crop is ambiguous (the Qwen path has produced "The quick
brown fox jumps over the lazy dog." for blank crops). Why it might not:
it is trained largely on IAM-style cursive, while these submissions are
often block capitals.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import torch
from PIL import Image

import ocr_pipeline

TROCR_MODEL_ID = os.getenv("TROCR_MODEL_ID", "microsoft/trocr-large-handwritten")

# Same meaning as the Qwen path's OCR_MIN_LINE_CONFIDENCE: below this, the
# caller should route the answer to human review rather than trust it.
MIN_CONFIDENCE = float(os.getenv("TROCR_MIN_CONFIDENCE", "0.15"))

# Lines per generate() call.
_BATCH_SIZE = int(os.getenv("TROCR_BATCH_SIZE", "8"))

_MAX_NEW_TOKENS = int(os.getenv("TROCR_MAX_TOKENS", "128"))


@dataclass
class _TrOCR:
    model: object
    processor: object


_MODELS: _TrOCR | None = None


def load_model() -> None:
    """Load TrOCR onto the GPU once, alongside (not instead of) Qwen."""
    global _MODELS
    if _MODELS is not None:
        return
    from transformers import TrOCRProcessor, VisionEncoderDecoderModel

    print(f"[TrOCR] Loading {TROCR_MODEL_ID}...")
    processor = TrOCRProcessor.from_pretrained(TROCR_MODEL_ID)
    model = VisionEncoderDecoderModel.from_pretrained(TROCR_MODEL_ID, torch_dtype=torch.float16)
    model.to("cuda")
    model.eval()
    _MODELS = _TrOCR(model=model, processor=processor)
    print("[TrOCR] Ready.")


def _transcribe_lines(line_images: list[Image.Image]) -> list[tuple[str, float]]:
    """Transcribe line crops, returning (text, confidence) per line."""
    assert _MODELS is not None
    results: list[tuple[str, float]] = []
    for start in range(0, len(line_images), _BATCH_SIZE):
        batch = [im.convert("RGB") for im in line_images[start:start + _BATCH_SIZE]]
        pixel_values = _MODELS.processor(images=batch, return_tensors="pt").pixel_values
        pixel_values = pixel_values.to("cuda", dtype=torch.float16)
        with torch.no_grad():
            out = _MODELS.model.generate(
                pixel_values,
                max_new_tokens=_MAX_NEW_TOKENS,
                num_beams=1,              # greedy, for reproducible output
                output_scores=True,
                return_dict_in_generate=True,
            )
        texts = _MODELS.processor.batch_decode(out.sequences, skip_special_tokens=True)
        # Confidence: the least certain token the decoder committed to on that
        # line — same definition the Qwen path reports.
        probs = torch.stack(out.scores, dim=1).softmax(dim=-1)
        chosen = out.sequences[:, 1:1 + probs.shape[1]]
        token_probs = probs.gather(2, chosen.unsqueeze(-1)).squeeze(-1)
        pad_id = _MODELS.processor.tokenizer.pad_token_id
        for row_ids, row_probs, text in zip(chosen.tolist(), token_probs, texts):
            real = [p for tid, p in zip(row_ids, row_probs.tolist()) if tid != pad_id]
            results.append((text.strip(), min(real) if real else 1.0))
    return results


def transcribe(
    image: Image.Image,
    single_line: bool = False,
) -> tuple[str, list[tuple[int, int, int, int]], bool]:
    """
    Transcribe one crop with TrOCR.

    single_line=True treats the whole crop as one line (identification answer
    boxes). Otherwise Surya — the same detector the Qwen path uses, loaded by
    ocr_pipeline — finds the lines first.

    Returns (text, boxes, low_confidence).
    """
    load_model()
    if single_line:
        lines = _transcribe_lines([image])
        text = lines[0][0] if lines else ""
        conf = lines[0][1] if lines else 1.0
        return text, [(0, 0, image.width, image.height)], conf < MIN_CONFIDENCE

    assert ocr_pipeline.MODELS is not None, "Surya not loaded"
    t0 = time.perf_counter()
    det_img = (
        image.convert("RGB") if os.getenv("SURYA_RAW_DETECT") == "1"
        else ocr_pipeline.preprocess_for_detection(image)
    )
    preds = ocr_pipeline.MODELS.surya_detector([det_img])
    boxes = ocr_pipeline._extract_surya_xyxy(preds[0] if preds else None)
    boxes = ocr_pipeline.merge_overlapping_boxes(boxes)
    boxes = sorted(boxes, key=lambda b: (b[1], b[0]))
    boxes = [b for b in boxes if ocr_pipeline._has_ink(image, b)]
    print(f"[TrOCR] Surya found {len(boxes)} lines in {time.perf_counter() - t0:.2f}s")
    if not boxes:
        return "", [], False

    crops = ocr_pipeline.crop_lines(image, boxes)
    t1 = time.perf_counter()
    lines = _transcribe_lines(crops)
    print(f"[TrOCR] transcribed {len(lines)} lines in {time.perf_counter() - t1:.2f}s")
    text = "\n".join(t for t, _ in lines)
    low_conf = any(c < MIN_CONFIDENCE for _, c in lines)
    return text, boxes, low_conf
