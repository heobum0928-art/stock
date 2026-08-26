@echo off
cd /d "%~dp0"
echo ============================================
echo  Install LLM helper for "Build inspection by writing"
echo  (online intent classifier - optional)
echo ============================================
echo.
echo [1/2] Installing anthropic SDK into .venv ...
rem Install the package directly (not via -r) so file encoding never breaks pip.
.venv\Scripts\python.exe -m pip install "anthropic>=0.40"
echo.
echo [2/2] Checking API key ...
if "%ANTHROPIC_API_KEY%"=="" (
  echo   *** ANTHROPIC_API_KEY is NOT set.
  echo   Set it once ^(replace sk-... with your key^):
  echo       setx ANTHROPIC_API_KEY "sk-..."
  echo   Then close and reopen this window / run_engine.bat.
) else (
  echo   ANTHROPIC_API_KEY is set. OK.
)
echo.
echo ============================================
echo  Done. Restart run_engine.bat to use the smarter writer.
echo  To turn it OFF anytime:  setx VISION_NL_LLM 0
echo  Worker text only is sent (never images). Logs stay on this PC.
echo ============================================
pause
