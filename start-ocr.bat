@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please follow OCR_SETUP.md to create .venv and install optional dependencies.
  pause
  exit /b 1
)
.venv\Scripts\python.exe server.py --enable-ocr
pause
