@echo off
REM Double-click to start the Football Probabilities dashboard and open it in your browser.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo First run: setting up Python environment...
    python -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || goto :error
)
REM open the browser after a few seconds so the server is ready first
start "" /min cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8000"
echo Dashboard running at http://127.0.0.1:8000  (close this window to stop it)
".venv\Scripts\python.exe" cli.py serve
goto :eof

:error
echo Setup failed. Make sure Python 3.11+ is installed: https://www.python.org/downloads/
pause
