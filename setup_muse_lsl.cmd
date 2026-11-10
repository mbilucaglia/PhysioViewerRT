@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv-muse\Scripts\python.exe" (
    py -3.12 -m venv .venv-muse
    if errorlevel 1 exit /b 1
)
".venv-muse\Scripts\python.exe" -m pip install -r muse_lsl\requirements.txt
if errorlevel 1 exit /b 1
echo Muse LSL is ready. Run run_muse_lsl.cmd to open the app.
