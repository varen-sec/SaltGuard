@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=py"
if exist ".venv\Scripts\python.exe" set "PYTHON=.venv\Scripts\python.exe"
echo [1/2] SaltGuard regression tests used for demo readiness
%PYTHON% -m pytest -q tests\test_phase46_integration.py tests\test_phase461_serial_pin.py tests\test_phase462_custom_local_resync.py
if errorlevel 1 (
  echo.
  echo TESTS FAILED or pytest unavailable. To diagnose:
  echo %PYTHON% -m pytest -v tests\test_phase462_custom_local_resync.py
  echo To install pytest: %PYTHON% -m pip install pytest
  pause
  exit /b 1
)
echo.
echo [2/2] Read-only live pre-demo check (Backend and Wokwi must be started)
%PYTHON% phase47_preflight.py
if errorlevel 1 (
  echo.
  echo BLOCKED: inspect reported problem. If Backend is not running, try:
  echo %PYTHON% phase47_preflight.py --offline
  pause
  exit /b 2
)
echo.
echo PASS: automated checks and live preflight. Manual demo still required.
pause
exit /b 0
