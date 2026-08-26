@echo off
chcp 65001 >nul
cd /d "%~dp0"
title EdgeAI 학습 스튜디오
rem 통합 홈(런처) 실행 — 라벨링/학습/평가/뷰어를 한 창에서.
if not exist "train\.venv\Scripts\python.exe" (
    echo [!] Python env not found: train\.venv - see SETUP.md first.
    pause
    exit /b 1
)
start "" "train\.venv\Scripts\pythonw.exe" "examples\_common\studio.py"
