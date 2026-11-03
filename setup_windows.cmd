@echo off
setlocal
call "%~dp0project.cmd" setup %*
set "SETUP_RESULT=%ERRORLEVEL%"
if not "%SETUP_RESULT%"=="0" echo Setup failed. Review the errors above.
if /I not "%~1"=="--non-interactive" pause
exit /b %SETUP_RESULT%
