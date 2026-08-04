# GrAId Demo / Smoke Test Checklist (Vast.ai remote OCR)

Current instance: **46802476** (2x RTX 5060 Ti, datacenter host) — Public IP `158.181.52.18` (Static).
OCR server runs on internal port `10100`, mapped to external port `43240`.

## Part 1 — Start the remote OCR server

1. Log into Vast.ai -> **Instances** page. Confirm instance **46802476** shows "Running."
   If stopped, click the power icon to start it back up (files + model cache persist on disk).
2. Click **Open** -> launch **Jupyter Terminal** (or open a new terminal tab if one is busy).
3. Check if the server is already running:
   ```bash
   curl http://localhost:10100/health
   ```
   If you get `{"status":"ok"}`, skip to step 5.
4. If not running, start it (files live directly in `/workspace`, the default directory,
   so no `cd` needed):
   ```bash
   tmux new -s ocr
   PORT=10100 python3 vast_ocr_server.py
   ```
   Wait for `Uvicorn running on http://0.0.0.0:10100`, then detach with `Ctrl+B` then `D`
   (or just open a new terminal tab if detach doesn't respond).
5. Verify it's reachable from outside the instance — from your own machine's browser or terminal:
   ```
   http://158.181.52.18:43240/health
   ```
   Should return `{"status":"ok"}`.

## Part 2 — Start the local backend

```powershell
cd "C:\Users\ASUS\OneDrive\Desktop\Files\John\GrAID-Repo"
.\run_graid.ps1
```
- Enter `GROQ_API_KEY` if prompted.
- Paste `http://158.181.52.18:43240` when asked for the remote OCR URL.
- Wait for `Starting GrAId at http://127.0.0.1:8000`.
- Open `http://127.0.0.1:8000` yourself first to confirm it loads before involving anyone else.

## Part 3 — Sharing the URL with groupmates

By default the backend only binds to `127.0.0.1` — not reachable by anyone but you, even on the
same WiFi.

- **Same room/WiFi:** run `ipconfig`, find your WiFi adapter's "IPv4 Address," and have groupmates
  browse to `http://<your-LAN-IP>:8000`. Requires changing `run_graid.ps1`'s last line from
  `--host 127.0.0.1` to `--host 0.0.0.0` first.
- **Different locations:** requires a tunneling tool (e.g. ngrok) to expose the local backend to
  the internet — separate setup, ask if this is actually needed.

## Part 0 — End of session (do this every time)

To avoid being billed while not actively working:

1. On the Instances page, click the black square (**Stop**) icon on instance 46802476.
   This pauses the GPU billing (~$0.36/hr) but keeps the disk (uploaded files + the ~15GB Qwen
   model cache) intact, so next startup skips the slow parts.
2. Check the instance's storage/disk price on its details page if you want the exact per-GB rate
   — it's a small fee compared to the running GPU rate.
3. Only start it back up right before your next demo/smoke test session (Part 1, step 1).

**Do not Destroy** the instance unless you're fully done with it for the thesis — that wipes
everything and the next session would need the full re-clone/upload/install/model-download setup
from scratch.
