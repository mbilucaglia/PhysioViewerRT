@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run setup_windows.cmd to install dependencies.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" main.py
if errorlevel 1 (
  echo The application exited with an error.
  pause
)
