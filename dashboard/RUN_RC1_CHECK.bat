@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo ERROR: .venv was not found.
  echo Run SETUP_RC1_TEST_ENV.bat first, or create .venv and install requirements-dev.txt.
  pause
  exit /b 1
)
"%PYTHON%" -m pytest --version >nul 2>nul
if errorlevel 1 (
  echo ERROR: pytest is missing from this project's .venv.
  echo Run SETUP_RC1_TEST_ENV.bat. This is an environment dependency, not a SaltGuard runtime failure.
  pause
  exit /b 1
)
echo [1/3] Targeted RC1 regression tests (18 tests)
"%PYTHON%" -m pytest -q tests\test_phase46_integration.py tests\test_phase461_serial_pin.py tests\test_phase462_custom_local_resync.py
if errorlevel 1 goto testfail
echo.
echo [2/3] Static firmware and Wokwi preflight (read-only)
"%PYTHON%" phase47_preflight.py --offline
if errorlevel 1 goto staticfail
echo.
echo [3/3] Live pre-demo check (Backend and Wokwi must be running)
"%PYTHON%" phase47_preflight.py
if errorlevel 1 goto livefail
echo.
echo RESULT: PASS
 echo RC1 preflight passed. Manual end-to-end demonstration is still required.
pause
exit /b 0
:testfail
echo.
echo FAIL: targeted regression tests failed. Read the pytest output above.
pause
exit /b 2
:staticfail
echo.
echo BLOCKED: firmware/Wokwi static check failed. Do not edit wiring blindly; inspect the listed invariant.
pause
exit /b 3
:livefail
echo.
echo BLOCKED: Backend/API/ESP32 live preflight failed. Ensure Backend and Wokwi are running and telemetry is fresh.
echo Offline static command: .venv\Scripts\python.exe phase47_preflight.py --offline
pause
exit /b 4
