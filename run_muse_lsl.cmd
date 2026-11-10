@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv-muse\Scripts\python.exe" (
    echo Run setup_muse_lsl.cmd first.
    exit /b 1
)
".venv-muse\Scripts\python.exe" -m muse_lsl
