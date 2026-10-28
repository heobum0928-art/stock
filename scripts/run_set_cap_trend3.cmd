@echo off
cd /d C:\coinbase
"C:\coinbase\.venv\Scripts\python.exe" scripts\set_cap_at.py "2026-10-29 03:30" trend3 440 >> logs\set_cap_at.stdout.txt 2>&1
