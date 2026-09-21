# GrAId Demo / Smoke Test Checklist (Vast.ai remote OCR)

The OCR server runs on internal port `10100`, mapped to a public IP + external port
that Vast.ai assigns. **Both can change when the instance restarts**, so never rely on a
port written down here — always read the current one with the command in Part 1, step 3.

## Part 1 — Start the remote OCR server

1. Log into Vast.ai -> **Instances**. Confirm the GrAId instance shows "Running."
   If stopped, click the power icon to start it back up (files + model cache persist on disk).
2. Click **Open** -> launch **Jupyter Terminal** (or open a new terminal tab if one is busy).
3. Get the current OCR URL — run this **on the instance**:
   ```bash
   echo "http://$PUBLIC_IPADDR:$VAST_TCP_PORT_10100"
   ```
   That printed URL is what `run_graid.ps1` asks for (Part 2). If it prints `http://:`,
   the variables aren't set in that shell — read them from the instance's environment:
   ```bash
   cat /proc/1/environ | tr '\0' '\n' | grep -E "PUBLIC_IPADDR|VAST_TCP_PORT_10100"
   ```
   As a last resort, the Instances page's IP button lists the same mapping as
   `<public IP>:<external port> -> 10100/tcp`.
4. Check if the server is already running:
   ```bash
   curl http://localhost:10100/health
   ```
   If you get `{"status":"ok"}`, skip to step 6. (`localhost:10100` only works *on the
   instance* — from your own PC, always use the URL from step 3.)
5. If not running, start it (files live directly in `/workspace`, the default directory,
   so no `cd` needed):
   ```bash
   tmux new -s ocr
   ```
   ```bash
   PORT=10100 python3 vast_ocr_server.py
   ```
   Wait for `Uvicorn running on http://0.0.0.0:10100`, then detach with `Ctrl+B` then `D`
   (or just open a new terminal tab if detach doesn't respond).
6. Verify it's reachable from outside the instance — from your own machine, using the
   URL from step 3:
   ```powershell
   curl.exe http://<public IP>:<external port>/health
   ```
   Should return `{"status":"ok"}`.

## Part 1b — Deploying code changes to the instance

The instance runs **manually uploaded copies** of the OCR files, not a git checkout, so
local edits have zero effect until the matching file is re-uploaded and the server
restarted. Which files matter:

| File | Upload when it changes | Notes |
|---|---|---|
| `ocr_pipeline.py` | yes | Shared by essay + identification OCR — re-uploading affects essay CER/WER |
| `id_ocr.py` | yes | Identification-only single-line OCR (used by `/ocr_id`) |
| `vast_ocr_server.py` | yes | The server itself (`/health`, `/ocr`, `/ocr_id`) |
| `ocr_alignment.py` | no | Cropping/alignment runs in the **local** backend; the instance never imports it |
| everything else | no | Grading, scoring, flags all run locally |

Upload steps:
1. Back up what you're replacing, so rollback is one command:
   ```bash
   cp /workspace/vast_ocr_server.py /workspace/vast_ocr_server.py.bak
   ```
2. Upload the changed file(s) into `/workspace` with the Jupyter file browser.
   Don't upload files that didn't change — especially `ocr_pipeline.py`, since essay OCR
   (and the CER/WER measured on it) depends on it.
3. Restart the server: `tmux attach -t ocr`, `Ctrl+C`, then the start command from
   Part 1, step 5. Models reload from the cache (fast), not from a fresh download.
4. Re-verify `/health` (Part 1, step 6).

Rollback: `cp /workspace/vast_ocr_server.py.bak /workspace/vast_ocr_server.py`, then restart.

## Part 2 — Start the local backend

```powershell
cd "C:\Users\ASUS\OneDrive\Desktop\Files\John\GrAID-Repo"
```
```powershell
.\run_graid.ps1
```
- Enter `GROQ_API_KEY` if prompted.
- Paste the URL from Part 1, step 3 when asked for the remote OCR URL.
- Rebuild the frontend first if it changed since the last build — the backend serves the
  prebuilt `frontend/dist`, so UI edits are invisible until you do:
  ```powershell
  cd frontend; npm run build; cd ..
  ```
- It prints two URLs when it starts:
  - `http://127.0.0.1:8000` — for you, on this machine.
  - `http://<your-LAN-IP>:8000` — **share this one with groupmates** on the same WiFi.
- Open the `127.0.0.1` URL yourself first to confirm it loads before sharing the LAN one.
- After an OCR-path change, re-run **OCR** on a submission, not just re-grade — re-grading
  reuses the stored OCR text.

### Groupmates in a different location (not the same WiFi)

The LAN URL won't reach them — use Cloudflare's quick tunnel instead. In a **second**
PowerShell window (leave `run_graid.ps1` running in the first one):
```powershell
& "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://localhost:8000
```
It prints a public link like `https://random-words.trycloudflare.com` — share that instead of
the LAN URL. Notes:
- The link changes every time you restart `cloudflared`, so re-share it each session.
- It's publicly reachable by anyone with the link while the tunnel is running — only share it
  with your groupmates, and close this window when done to shut it off.
- Keep both PowerShell windows open at the same time (backend + tunnel).

## Part 0 — End of session (do this every time)

To avoid being billed while not actively working:

1. On the Instances page, click the black square (**Stop**) icon on the instance.
   This pauses the GPU billing (~$0.20/hr) but keeps the disk (uploaded files + the ~15GB Qwen
   model cache) intact, so next startup skips the slow parts.
2. Check the instance's storage/disk price on its details page if you want the exact per-GB rate
   — it's a small fee compared to the running GPU rate.
3. Only start it back up right before your next demo/smoke test session (Part 1, step 1).

**Do not Destroy** the instance unless you're fully done with it for the thesis — that wipes
everything and the next session would need the full re-upload/install/model-download setup
from scratch (see Part 4).

## Part 3 — Troubleshooting

### A code fix doesn't seem to apply / weird silent errors

If you restart the local backend after a code change and the bug still happens, but the
PowerShell terminal you're watching shows nothing when you trigger it — you may have a second,
stale `run_graid.ps1` still running in another window from earlier, and your browser is talking to
that old process instead of the one you just restarted. Check for this before assuming the fix
didn't work:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object OwningProcess
```

If this lists **more than one** process ID, you've found the problem. Check what each one is:
```powershell
Get-Process -Id <each-id-from-above>
```
Kill the stale one (keep the one matching the `Started server process [<id>]` line in the
terminal you actually want):
```powershell
Stop-Process -Id <stale-id> -Force
```
Re-run the `Get-NetTCPConnection` check to confirm only one remains, then retry.

Also check, in order: is the OCR URL you pasted the *current* one (Part 1, step 3)? Did the
change touch a file the instance runs (Part 1b)? Is the frontend rebuilt?

### Other common ones

- **`Unable to connect` from your PC, but `/health` works on the instance** — the port changed
  after a restart. Re-read it (Part 1, step 3) and restart the backend with the new URL.
- **Identification answers return 404-ish behaviour / a `no /ocr_id endpoint` warning in the
  backend log** — the instance still runs a build without `/ocr_id`. Upload `id_ocr.py` +
  `vast_ocr_server.py` and restart (Part 1b). Grading keeps working meanwhile via the fallback.
- **A malformed `GROQ_API_KEY`** (stray whitespace from a copy-paste) shows up as a generic
  "Connection error", not a clean 401.

## Part 4 — Setting up a brand-new instance

Only needed if the old instance was destroyed or you're renting a replacement.

1. **Rent:** pick an official **PyTorch (CUDA 12.8+)** template — the RTX 5060 Ti is Blackwell and
   older CUDA images can't use it. Before renting, edit the template:
   - **Ports:** add `10100` (or `-p 10100:10100` in Docker options). **This cannot be added after
     the instance is created.**
   - **Disk:** at least 50 GB (the Qwen model alone is ~15 GB).
   - 1x GPU with 12 GB+ VRAM is enough — the model is pinned to a single GPU.
2. **Verify the GPU:**
   ```bash
   nvidia-smi
   ```
   ```bash
   python3 -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
   ```
   Must print `True`. If not, the template's PyTorch is too old — destroy and pick another.
3. **Upload** `vast_ocr_server.py`, `ocr_pipeline.py`, `id_ocr.py` and `requirements-vast.txt`
   into `/workspace`.
4. **Install dependencies:**
   ```bash
   pip install -r /workspace/requirements-vast.txt
   ```
   Use `requirements-vast.txt`, **not** the full `requirements.txt`: the full file installs
   `torch`/`torchvision`, which would replace the template's CUDA-matched build (symptom:
   `torch.cuda.is_available()` turns `False`), plus a pile of packages that only the local
   backend needs. Re-run the torch check from step 2 afterwards — if it now prints `False`,
   something replaced torch.
5. **Start the server** (Part 1, step 5). The first start downloads ~15 GB of model weights into
   `/workspace/graid_model_cache` and can take 10-20 minutes; later starts read the cache.
6. **Get the URL** (Part 1, step 3) and continue from Part 2.
