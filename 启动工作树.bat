@echo off
rem cogtree viewer launcher: kill stale viewers first, then start minimized + open browser
cd /d "%~dp0"
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8765 " ^| findstr LISTENING') do taskkill /PID %%p /F >nul 2>&1
start "cogtree-viewer" /min python -m cogtree.viewer
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8765/"
