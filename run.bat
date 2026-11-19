@echo off
REM KidsNote Alimjang Downloader - Windows launcher
REM Double-click this file. It creates .venv, installs packages, installs Chromium, runs app.py
REM This file must stay ASCII-only. Do NOT put Korean in .bat files.
REM cmd.exe reads .bat as CP949 before chcp takes effect, so Korean breaks it.
chcp 65001 >nul
cd /d "%~dp0"
title KidsNote Alimjang Downloader

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found.
  echo Install Python 3.10+ from https://www.python.org/downloads/
  echo During install, check "Add python.exe to PATH".
  pause
  exit /b 1
)

if not exist ".venv" (
  echo [1/4] Creating virtualenv .venv ...
  python -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Failed to create .venv. Check Python install.
    pause
    exit /b 1
  )
)

call ".venv\Scripts\activate.bat"

echo [2/4] Installing packages ...
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] pip install failed.
  pause
  exit /b 1
)

echo [3/4] Installing Chromium for Playwright ... (slow on first run only)
python -m playwright install chromium
if errorlevel 1 (
  echo [ERROR] Chromium install failed. Check internet.
  pause
  exit /b 1
)

echo [4/4] Starting app ...
python app.py
if errorlevel 1 (
  echo.
  echo App exited with error. See message above.
  pause
)
