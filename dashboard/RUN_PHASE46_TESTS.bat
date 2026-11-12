@echo off
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -m pytest -q tests\test_phase46_integration.py
) else (
  py -m pytest -q tests\test_phase46_integration.py
)
if errorlevel 1 (
 echo.
 echo Tests FAILED or pytest missing. Install: py -m pip install pytest
)
pause
