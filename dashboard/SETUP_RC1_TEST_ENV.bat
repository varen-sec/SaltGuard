@echo off
setlocal
cd /d "%~dp0"
echo SaltGuard RC1 - setup test environment
if not exist ".venv\Scripts\python.exe" (
  where py >nul 2>nul
  if errorlevel 1 (
    echo ERROR: Python launcher 'py' not found. Install Python 3.11+ with PATH support.
    pause
    exit /b 1
  )
  py -3 -m venv .venv
  if errorlevel 1 goto fail
)
echo Installing RC1 test dependencies into .venv...
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
if errorlevel 1 goto fail
echo.
echo PASS: test environment ready.
echo Run RUN_RC1_CHECK.bat after Backend and Wokwi are started.
pause
exit /b 0
:fail
echo.
echo ERROR: Could not prepare test environment. Check Python and Internet connection.
pause
exit /b 1
