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
- It prints two URLs when it starts:
  - `http://127.0.0.1:8000` — for you, on this machine.
  - `http://<your-LAN-IP>:8000` — **share this one with groupmates** on the same WiFi.
- Open the `127.0.0.1` URL yourself first to confirm it loads before sharing the LAN one.

### Groupmates in a different location (not the same WiFi)

The LAN URL won't reach them — use Cloudflare's quick tunnel instead. In a **second** PowerShell
window (leave `run_graid.ps1` running in the first one):
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

1. On the Instances page, click the black square (**Stop**) icon on instance 46802476.
   This pauses the GPU billing (~$0.36/hr) but keeps the disk (uploaded files + the ~15GB Qwen
   model cache) intact, so next startup skips the slow parts.
2. Check the instance's storage/disk price on its details page if you want the exact per-GB rate
   — it's a small fee compared to the running GPU rate.
3. Only start it back up right before your next demo/smoke test session (Part 1, step 1).

**Do not Destroy** the instance unless you're fully done with it for the thesis — that wipes
everything and the next session would need the full re-clone/upload/install/model-download setup
from scratch.

## Troubleshooting — a code fix doesn't seem to apply / weird silent errors

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
