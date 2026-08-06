import io
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pydantic import BaseModel

import ocr_pipeline
from database import init_db
from job_queue import start_worker
from routers.api_v1 import router as api_v1_router

_FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"

# Set SKIP_MODEL_LOAD=1 to start the server without loading Qwen/Surya.
# All data-platform endpoints (/api/v1/*) work normally.
# OCR endpoints (/extract, /api/v1/submissions/{id}/ocr) will return 503.
_SKIP_MODEL_LOAD = os.getenv("SKIP_MODEL_LOAD", "0") == "1"


class ExtractResponse(BaseModel):
    text: str
    boxed_image_png_base64: str


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        init_db()
    except Exception as e:
        print(f"\n[STARTUP ERROR] Database init failed: {e}\n")
        raise

    if _SKIP_MODEL_LOAD:
        print("[Models] SKIP_MODEL_LOAD=1 — skipping model load. OCR endpoints will return 503.")
    else:
        try:
            ocr_pipeline.load_models()
        except Exception as e:
            print(f"\n[STARTUP ERROR] Model loading failed: {e}\n")
            raise

    await start_worker()
    print("[Queue] Background OCR/grading queue worker started.")

    yield


app = FastAPI(title="GrAId — AI-Powered Exam Grading Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_v1_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/extract", response_model=ExtractResponse)
async def extract(file: UploadFile = File(...)) -> ExtractResponse:
    if ocr_pipeline.MODELS is None:
        raise HTTPException(status_code=503, detail="Models not loaded yet")

    if file.content_type and not (
        file.content_type.startswith("image/") or file.content_type == "application/octet-stream"
    ):
        raise HTTPException(status_code=400, detail=f"Unsupported content-type: {file.content_type}")

    raw = await file.read()
    try:
        original = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not decode image: {e}") from e

    full_text, _boxes, boxed = ocr_pipeline.run_ocr_pipeline(original)
    return ExtractResponse(
        text=full_text,
        boxed_image_png_base64=ocr_pipeline.encode_png_base64(boxed),
    )


# ── Serve built frontend (production) ────────────────────────────────────────
# Only active when `frontend/dist` exists (i.e. after `npm run build`).
# In dev, run `npm run dev` separately and use http://localhost:5173.
if _FRONTEND_DIST.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=str(_FRONTEND_DIST / "assets")),
        name="frontend-assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str) -> FileResponse:
        """Catch-all: serve index.html for any unmatched path (SPA routing)."""
        return FileResponse(str(_FRONTEND_DIST / "index.html"))
