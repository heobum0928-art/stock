while ($true) {
  Start-Sleep -Seconds 1800
  $env:PYTHONIOENCODING = 'utf-8'
  & "C:\coinbase\.venv\Scripts\python.exe" "C:\coinbase\scripts\status_heartbeat.py" *>> "C:\coinbase\logs\status_heartbeat.log"
}
