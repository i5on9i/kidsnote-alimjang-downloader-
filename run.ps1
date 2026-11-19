# KidsNote Alimjang Downloader - PowerShell launcher (alternative to run.bat)
# Usage: Right-click -> Run with PowerShell, or: powershell -ExecutionPolicy Bypass -File .\run.ps1
# ASCII-only on purpose.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  Write-Host "[ERROR] Python not found. Install Python 3.10+ and check Add python.exe to PATH."
  Read-Host "Press Enter to exit"
  exit 1
}
if (-not (Test-Path ".venv")) {
  Write-Host "[1/4] Creating .venv ..."
  python -m venv .venv
}
& ".venv\Scripts\Activate.ps1"
Write-Host "[2/4] Installing packages ..."
python -m pip install --upgrade pip
pip install -r requirements.txt
Write-Host "[3/4] Installing Chromium ..."
python -m playwright install chromium
Write-Host "[4/4] Starting app ..."
python app.py
