"""
vast_ocr_server.py — GrAId Remote OCR Server for a Vast.ai GPU instance.

Serves the /health and /ocr contract that ocr_pipeline.py's
`_run_remote_ocr_pipeline()` expects from REMOTE_OCR_URL:
  - GET  /health -> 200 OK once models are loaded.
  - POST /ocr (multipart `file`) -> {"text": str, "boxes": [[x1,y1,x2,y2], ...],
                                      "boxed_image_png_base64": str,
                                      "low_confidence": bool}

This script imports ocr_pipeline.py directly rather than duplicating its
logic, so behavior is guaranteed identical to the local-load path the
thesis's CER/WER evaluation validates against.

Usage (on the Vast.ai instance, inside the repo checkout):
    pip install -r requirements.txt
    python vast_ocr_server.py

Then, on the machine running the FastAPI backend:
    REMOTE_OCR_URL=http://<instance public IP>:<forwarded port>
"""
from __future__ import annotations

import os

# Persistent model cache — must be set BEFORE importing anything from
# transformers/huggingface_hub (they read HF_HOME at import time, not
# lazily). Point this at Vast.ai's persistent volume (commonly /workspace)
# so the ~15GB Qwen download only happens once per instance, not once per
# script restart. Override with GRAID_MODEL_CACHE if your instance mounts
# persistent storage somewhere else.
CACHE_DIR = os.environ.get("GRAID_MODEL_CACHE", "/workspace/graid_model_cache")
os.makedirs(CACHE_DIR, exist_ok=True)
os.environ["HF_HOME"] = CACHE_DIR
os.environ["HF_HUB_CACHE"] = os.path.join(CACHE_DIR, "hub")

# This process IS the OCR server — make sure it always takes ocr_pipeline's
# local-load branch, never tries to delegate to another remote server.
os.environ.pop("REMOTE_OCR_URL", None)

import io  # noqa: E402
import time  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from typing import AsyncIterator  # noqa: E402

import torch  # noqa: E402
from fastapi import FastAPI, File, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from PIL import Image  # noqa: E402

import ocr_pipeline  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    print("[Models] Checking CUDA...")
    if not torch.cuda.is_available():
        raise RuntimeError(
            "No GPU detected on this instance. Confirm you rented a GPU-enabled "
            "Vast.ai instance and that `nvidia-smi` works before starting this server."
        )
    print(f"[Models] CUDA OK — {torch.cuda.get_device_name(0)}")
    ocr_pipeline.load_models(force_local=True)
    yield


app = FastAPI(title="GrAId Remote OCR Server (Vast.ai)", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    if ocr_pipeline.MODELS is None:
        raise HTTPException(status_code=503, detail="Models not loaded")
    return {"status": "ok"}


@app.post("/ocr")
async def ocr(file: UploadFile = File(...), include_boxed_image: bool = True) -> JSONResponse:
    if ocr_pipeline.MODELS is None:
        raise HTTPException(status_code=503, detail="Models not loaded")

    t_start = time.perf_counter()
    raw = await file.read()
    try:
        original = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image: {e}") from e

    full_text, boxes, boxed, low_confidence = ocr_pipeline.run_ocr_pipeline(original)
    # Every grading call site discards the annotated debug image — only the
    # OCR Tool page actually displays it. Skipping the PNG encode + base64
    # (which inflates size ~33%) saves real time on both ends of the wire
    # for the calls that never use it.
    boxed_b64 = ocr_pipeline.encode_png_base64(boxed) if include_boxed_image else ""
    response = JSONResponse({
        "text": full_text,
        "boxes": [list(b) for b in boxes],
        "boxed_image_png_base64": boxed_b64,
        "low_confidence": low_confidence,
    })
    # Everything from receiving the upload to building the response — compare
    # this against the local machine's round-trip time for the same request
    # to see how much of the gap is network transfer vs. this server's work.
    print(f"[Timing] /ocr request handled server-side in {time.perf_counter() - t_start:.2f}s")
    return response


@app.post("/ocr_id")
async def ocr_id(file: UploadFile = File(...)) -> JSONResponse:
    """
    Identification answers: read the whole answer box as one line, skipping
    Surya line detection entirely (see id_ocr.py for why).

    Separate from /ocr on purpose — essay OCR keeps running the untouched
    run_ocr_pipeline path above, so its CER/WER stay comparable.
    """
    import id_ocr

    if ocr_pipeline.MODELS is None:
        raise HTTPException(status_code=503, detail="Models not loaded")

    t_start = time.perf_counter()
    raw = await file.read()
    try:
        original = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image: {e}") from e

    text, confidence = id_ocr.transcribe_answer_box(original)
    print(
        f"[Timing] /ocr_id request handled server-side in "
        f"{time.perf_counter() - t_start:.2f}s (confidence {confidence:.3f})"
    )
    return JSONResponse({
        "text": text,
        "boxes": [[0, 0, original.width, original.height]],
        "confidence": confidence,
        "low_confidence": confidence < id_ocr.MIN_CONFIDENCE,
    })


@app.post("/ocr_trocr")
async def ocr_trocr(file: UploadFile = File(...), single_line: bool = False) -> JSONResponse:
    """
    Experimental: transcribe with TrOCR (a handwriting-specialised model)
    instead of Qwen, for benchmarking against /ocr and /ocr_id.

    Additive only — /ocr and /ocr_id are untouched, and nothing in the app
    calls this. The model loads on first request, so the first call is slow.
    """
    import trocr_ocr

    if ocr_pipeline.MODELS is None:
        raise HTTPException(status_code=503, detail="Models not loaded")

    t_start = time.perf_counter()
    raw = await file.read()
    try:
        original = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image: {e}") from e

    text, boxes, low_confidence = trocr_ocr.transcribe(original, single_line=single_line)
    print(f"[Timing] /ocr_trocr handled server-side in {time.perf_counter() - t_start:.2f}s")
    return JSONResponse({
        "text": text,
        "boxes": [list(b) for b in boxes],
        "low_confidence": low_confidence,
        "model": trocr_ocr.TROCR_MODEL_ID,
    })


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
