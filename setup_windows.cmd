@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher not found. Install Python 3.11 or 3.12 from python.org, then retry.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  py -3.11 -m venv .venv 2>nul
  if errorlevel 1 py -3.12 -m venv .venv
  if errorlevel 1 (
    echo Failed to create virtual environment. Install Python 3.11 or 3.12.
    pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto error
echo.
echo Setup complete. Run start_windows.cmd and optionally simulate_windows.cmd.
pause
exit /b 0
:error
echo Installation failed. Review the messages above.
pause
exit /b 1
