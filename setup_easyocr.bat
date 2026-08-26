@echo off
cd /d "%~dp0"
echo ============================================
echo  Install EasyOCR (deep-learning Korean OCR)
echo  - accurate but large (incl. torch, hundreds of MB ~ 1GB)
echo  - takes a few minutes depending on network. Do NOT close.
echo ============================================
echo.
if not exist ".venv\Scripts\python.exe" (
  echo *** .venv not found. Run run_engine.bat once first.
  pause
  exit /b 1
)
echo Installing...
.venv\Scripts\python.exe -m pip install easyocr
if errorlevel 1 (
  echo.
  echo *** install FAILED - screenshot this and send to Claude.
  pause
  exit /b 1
)
echo.
echo Pre-downloading Korean model...  (first time only, 1-2 min)
.venv\Scripts\python.exe -c "import easyocr; easyocr.Reader(['ko','en'], gpu=False); print('model ready')"
echo.
echo ============================================
echo  Done!  Now:
echo   1) restart run_engine.bat
echo   2) in OCR node properties set  OCR engine = easyocr
echo   3) first run is slow (model load), fast after
echo ============================================
pause
