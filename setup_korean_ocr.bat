@echo off
cd /d "%~dp0"
echo ============================================
echo  Install Korean OCR data (kor + eng)
echo ============================================
echo.
if not exist tessdata mkdir tessdata
echo [1/2] Downloading Korean data (kor)...  ~12MB
powershell -Command "try { Invoke-WebRequest -Uri 'https://github.com/tesseract-ocr/tessdata/raw/main/kor.traineddata' -OutFile 'tessdata\kor.traineddata' -UseBasicParsing; Write-Host '   kor OK' } catch { Write-Host '   *** kor download FAILED:' $_.Exception.Message }"
echo [2/2] Checking English data (eng)...
if not exist tessdata\eng.traineddata powershell -Command "try { Invoke-WebRequest -Uri 'https://github.com/tesseract-ocr/tessdata/raw/main/eng.traineddata' -OutFile 'tessdata\eng.traineddata' -UseBasicParsing } catch {}"
echo.
if exist tessdata\kor.traineddata (
  echo ============================================
  echo  Done!  Restart run_engine.bat for Korean OCR.
  echo  ^(OCR node: lang=kor or eng+kor, preprocess=on, binarize=adaptive^)
  echo ============================================
) else (
  echo *** kor download failed. Check internet or screenshot and send to Claude.
)
pause
