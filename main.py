import base64
import io
import os
from dataclasses import dataclass
from typing import Any, Optional

import cv2
import numpy as np
import torch
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageDraw
from pydantic import BaseModel
from qwen_vl_utils import process_vision_info
from transformers import (
    AutoModelForVision2Seq,
    AutoProcessor,
    BitsAndBytesConfig,
)

# Surya line detection
from surya.detection import DetectionPredictor


QWEN_MODEL_ID = os.getenv("QWEN_MODEL_ID", "Qwen/Qwen2.5-VL-7B-Instruct")


class ExtractResponse(BaseModel):
    text: str
    boxed_image_png_base64: str


@dataclass
class Models:
    # Surya
    surya_detector: Any
    # Qwen
    qwen_model: Any
    qwen_processor: Any


app = FastAPI(title="Handwritten Test Paper OCR Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


MODELS: Optional[Models] = None


def _pil_to_cv2_bgr(img: Image.Image) -> np.ndarray:
    rgb = np.array(img.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _cv2_bgr_to_pil(img_bgr: np.ndarray) -> Image.Image:
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def preprocess_for_detection(img: Image.Image) -> Image.Image:
    """
    Preprocess for line detection:
    - grayscale
    - denoise
    - adaptive threshold
    Return PIL RGB (Surya expects PIL Images).
    """
    bgr = _pil_to_cv2_bgr(img)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    den = cv2.fastNlMeansDenoising(gray, None, h=12, templateWindowSize=7, searchWindowSize=21)
    thr = cv2.adaptiveThreshold(
        den,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        15,
    )
    rgb = cv2.cvtColor(thr, cv2.COLOR_GRAY2RGB)
    return Image.fromarray(rgb)


def draw_boxes(image: Image.Image, boxes_xyxy: list[tuple[int, int, int, int]]) -> Image.Image:
    out = image.convert("RGB").copy()
    draw = ImageDraw.Draw(out)
    for (x1, y1, x2, y2) in boxes_xyxy:
        draw.rectangle([x1, y1, x2, y2], outline=(255, 0, 0), width=2)
    return out


def _encode_png_base64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _extract_surya_xyxy(pred: Any) -> list[tuple[int, int, int, int]]:
    """
    Surya returns prediction objects with .bboxes iterable.
    Each bbox has .bbox as [x1,y1,x2,y2] (rect) in image coords.
    """
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


def crop_lines(original_rgb: Image.Image, boxes_xyxy: list[tuple[int, int, int, int]]) -> list[Image.Image]:
    w, h = original_rgb.size
    crops: list[Image.Image] = []
    for (x1, y1, x2, y2) in boxes_xyxy:
        x1c, y1c = max(0, x1), max(0, y1)
        x2c, y2c = min(w, x2), min(h, y2)
        if x2c <= x1c or y2c <= y1c:
            continue
        crops.append(original_rgb.crop((x1c, y1c, x2c, y2c)))
    return crops


def qwen_ocr_lines(line_images: list[Image.Image]) -> list[str]:
    assert MODELS is not None

    # Simple prompt for line-level transcription; tune later if needed.
    prompt = "Transcribe the handwritten text in this image line. Output only the text."

    texts: list[str] = []
    for img in line_images:
        # Qwen2.5-VL expects image placeholders in the text. The safest way is the chat template
        # + qwen-vl-utils vision preprocessing helper.
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

        # Remove the prompt tokens and decode only newly generated tokens.
        prompt_len = inputs["input_ids"].shape[1]
        gen_only = output_ids[:, prompt_len:]
        decoded = MODELS.qwen_processor.batch_decode(gen_only, skip_special_tokens=True)
        txt = decoded[0].strip()
        texts.append(txt)

    return texts


@app.on_event("startup")
def startup_load_models() -> None:
    global MODELS

    if MODELS is not None:
        return

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA not available. Install a CUDA-enabled PyTorch build and NVIDIA drivers.")

    # Surya detector
    # Note: Surya's public API changed across versions; DetectionPredictor works for surya-ocr==0.13.1.
    surya_detector = DetectionPredictor()
    # Move to GPU if available
    if torch.cuda.is_available():
        try:
            # Surya's predictor `.to(...)` is in-place (returns None), so don't reassign.
            surya_detector.to("cuda")
        except Exception:
            # If moving fails, it'll run on CPU (slower) but keep the server alive.
            pass

    # Qwen2.5-VL 4-bit
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.float16,
    )

    qwen_processor = AutoProcessor.from_pretrained(QWEN_MODEL_ID, trust_remote_code=True)
    qwen_model = AutoModelForVision2Seq.from_pretrained(
        QWEN_MODEL_ID,
        quantization_config=bnb_config,
        device_map="auto",
        torch_dtype=torch.float16,
        trust_remote_code=True,
    )
    qwen_model.eval()

    MODELS = Models(
        surya_detector=surya_detector,
        qwen_model=qwen_model,
        qwen_processor=qwen_processor,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/extract", response_model=ExtractResponse)
async def extract(file: UploadFile = File(...)) -> ExtractResponse:
    if MODELS is None:
        raise HTTPException(status_code=503, detail="Models not loaded yet")

    # Some clients (including Python requests) may send uploads as application/octet-stream.
    # We accept that and rely on Pillow to validate/parse the actual bytes.
    if file.content_type and not (
        file.content_type.startswith("image/") or file.content_type == "application/octet-stream"
    ):
        raise HTTPException(status_code=400, detail=f"Unsupported content-type: {file.content_type}")

    raw = await file.read()
    try:
        original = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not decode image: {e}") from e

    det_img = preprocess_for_detection(original)

    # Surya expects list of PIL images; returns list of TextDetectionResult
    preds = MODELS.surya_detector([det_img])
    pred0 = preds[0] if preds else None
    boxes = _extract_surya_xyxy(pred0)

    # Crop from original (not binarized), keep reading order top-to-bottom.
    boxes_sorted = sorted(boxes, key=lambda b: (b[1], b[0]))
    line_crops = crop_lines(original, boxes_sorted)

    if not line_crops:
        boxed = draw_boxes(original, boxes_sorted)
        return ExtractResponse(text="", boxed_image_png_base64=_encode_png_base64(boxed))

    line_texts = qwen_ocr_lines(line_crops)

    # Minimal cleanup: join lines, normalize whitespace.
    clean_lines = [" ".join(t.split()) for t in line_texts if t and t.strip()]
    full_text = "\n".join(clean_lines).strip()

    boxed = draw_boxes(original, boxes_sorted)
    return ExtractResponse(text=full_text, boxed_image_png_base64=_encode_png_base64(boxed))

