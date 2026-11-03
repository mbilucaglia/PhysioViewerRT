@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -B tools\project_env.py %*
  exit /b
)
py -3.12 -c "import sys; assert sys.maxsize > 2**32" >nul 2>nul
if not errorlevel 1 (
  py -3.12 -B tools\project_env.py %*
  exit /b
)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
  "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -B tools\project_env.py %*
  exit /b
)
python -c "import sys; assert sys.version_info[:2] in ((3,11),(3,12)) and sys.maxsize > 2**32" >nul 2>nul
if not errorlevel 1 (
  python -B tools\project_env.py %*
  exit /b
)
py -3.11 -c "import sys; assert sys.maxsize > 2**32" >nul 2>nul
if not errorlevel 1 (
  py -3.11 -B tools\project_env.py %*
  exit /b
)
echo Install Python 3.12 x64, then run project.cmd setup.
exit /b 1
