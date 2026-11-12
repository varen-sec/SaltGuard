@echo off
setlocal
cd /d "%~dp0"
echo ===============================================
echo  SALTGUARD MVP 1.1 - FARMER / EXPERT / DEMO
echo ===============================================
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  set "PYTHON=py -3"
) else (
  set "PYTHON=python"
)
if not exist .venv\Scripts\python.exe (
  echo [1/3] Tao moi truong Python...
  %PYTHON% -m venv .venv
  if errorlevel 1 goto fail
)
echo [2/3] Cai thu vien mien phi...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto fail
echo [3/3] Khoi dong Web Dashboard tai http://127.0.0.1:8000
echo Gio Wokwi chay va ket noi MQTT; mo dia chi tren trinh duyet.
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
exit /b 0
:fail
echo Co loi. Xem thong bao phia tren. Kiem tra Python va Internet.
pause
exit /b 1
