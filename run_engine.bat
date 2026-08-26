@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONPATH=engine;proto\generated
rem Korean OCR: prefer local tessdata (incl. kor) if present
if exist "%~dp0tessdata\kor.traineddata" set TESSDATA_PREFIX=%~dp0tessdata
echo [Vision Engine] gRPC server on :50051  (keep this window open; close to stop)
.venv\Scripts\python.exe -m vision_engine.server
pause
