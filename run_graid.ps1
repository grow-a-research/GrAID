# GrAId - one-command startup for demos / the thesis defense.
#
# Usage: open PowerShell in this folder and run:  .\run_graid.ps1
#
# What it does:
#   1. Checks for GROQ_API_KEY (needed for AI grading) - prompts once if missing.
#   2. Asks for the current REMOTE_OCR_URL (the Vast.ai OCR server's address).
#   3. Starts the backend, which also serves the built frontend at the same
#      URL - one process, one browser tab, nothing else to juggle live.
#
# Before defense day:
#   - Set GROQ_API_KEY permanently (System Properties > Environment Variables)
#     so you never have to paste it live in front of panelists.
#   - Rebuild the frontend if you've changed it since the last build:
#       cd frontend; npm run build
#   - Start the Vast.ai instance FIRST and confirm vast_ocr_server.py is
#     running (see VAST_AI_DEMO_CHECKLIST.md), get its REMOTE_OCR_URL,
#     THEN run this script.

$RepoRoot = $PSScriptRoot
Set-Location $RepoRoot

if (-not $env:GROQ_API_KEY) {
    Write-Host "GROQ_API_KEY is not set for this terminal session." -ForegroundColor Yellow
    $secure = Read-Host "Paste your Groq API key (hidden input, free key at console.groq.com)" -AsSecureString
    $plain = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    )
    if ($plain) { $env:GROQ_API_KEY = $plain }
} else {
    Write-Host "GROQ_API_KEY already set for this session." -ForegroundColor Green
}

$RemoteUrl = Read-Host "Paste the current REMOTE_OCR_URL from your Vast.ai OCR server (leave blank to skip remote OCR)"
# Be forgiving if the whole printed line (including the "REMOTE_OCR_URL=" prefix) got pasted.
if ($RemoteUrl -match '^REMOTE_OCR_URL=(.+)$') {
    $RemoteUrl = $Matches[1]
}
$RemoteUrl = $RemoteUrl.Trim()
if ($RemoteUrl) {
    $env:REMOTE_OCR_URL = $RemoteUrl
    Write-Host "Using remote OCR server: $RemoteUrl" -ForegroundColor Green
} else {
    Write-Host "No REMOTE_OCR_URL given - OCR endpoints will return 503 until one is set." -ForegroundColor Yellow
}

$LanIp = (Get-NetIPAddress -AddressFamily IPv4 -PrefixOrigin Dhcp, Manual -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike '169.254.*' } | Select-Object -First 1 -ExpandProperty IPAddress)

Write-Host ""
Write-Host "Starting GrAId (backend + built frontend, single process)..." -ForegroundColor Cyan
Write-Host "  On this machine: http://127.0.0.1:8000" -ForegroundColor Cyan
if ($LanIp) {
    Write-Host "  Share with groupmates on the same WiFi: http://${LanIp}:8000" -ForegroundColor Cyan
} else {
    Write-Host "  Could not detect a LAN IP to share - run ipconfig manually if needed." -ForegroundColor Yellow
}
& "$RepoRoot\venv\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000
