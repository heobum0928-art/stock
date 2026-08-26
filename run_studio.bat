@echo off
cd /d "%~dp0"
echo [Vision Studio] building latest and launching...  (start run_engine.bat first)
dotnet run --project studio\VisionStudio\VisionStudio.csproj -c Release
pause
