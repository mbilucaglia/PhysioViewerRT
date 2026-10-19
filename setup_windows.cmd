@echo off
setlocal
cd /d "%~dp0"
set "PYTHON_CMD="

rem Prefer an installed, compatible 64-bit Python on PATH (no py launcher required).
python -c "import sys; sys.exit(0 if sys.version_info[:2] in ((3,11),(3,12)) and sys.maxsize > 2**32 else 1)" >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=python"

rem Fallback: Windows Python launcher if it is installed.
if not defined PYTHON_CMD (
  py -3.12 -c "import sys; sys.exit(0 if sys.maxsize > 2**32 else 1)" >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=py -3.12"
)
if not defined PYTHON_CMD (
  py -3.11 -c "import sys; sys.exit(0 if sys.maxsize > 2**32 else 1)" >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=py -3.11"
)

if not defined PYTHON_CMD (
  echo No compatible 64-bit Python 3.11 or 3.12 detected.
  echo Run: python --version
  echo Run: py --list
  echo If Python is installed, check PATH or install a compatible version.
  pause
  exit /b 1
)

echo Using %PYTHON_CMD%
if not exist ".venv\Scripts\python.exe" (
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 goto error
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
