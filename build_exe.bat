@echo off
REM Build KidsnoteAlimjangDownloader.exe
REM Output: dist\KidsnoteAlimjangDownloader.exe
REM This file must stay ASCII-only.
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
  echo Run run.bat once first to create .venv.
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
pip install pyinstaller
python -m playwright install chromium
pyinstaller --noconfirm --onefile --windowed --name KidsnoteAlimjangDownloader --collect-all playwright app.py
echo.
echo Done: dist\KidsnoteAlimjangDownloader.exe
pause
