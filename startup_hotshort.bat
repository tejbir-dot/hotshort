@echo off
setlocal

set "ROOT=C:\Users\n\Documents\hotshort"
set "VENV_PY=%ROOT%\.venv\Scripts\python.exe"
set "PORT=10000"
set "LOCAL_WORKER_PORT=5000"

cd /d "%ROOT%"

if not exist "%VENV_PY%" (
  echo Virtual environment python not found at:
  echo %VENV_PY%
  pause
  exit /b 1
)

echo Configuring local-first hybrid pipeline...
set "LOCAL_HTTP_WORKER=1"
set "LOCAL_WORKER_URL=http://127.0.0.1:%LOCAL_WORKER_PORT%/run"
set "LOCAL_WORKER_MAX_CONCURRENCY=1"
set "LOCAL_WORKER_MAX_QUEUE=0"

echo Starting RunPod worker...
start "HotShort Worker" /d "%ROOT%" cmd /k ""%VENV_PY%" runpodworker.py"

echo Starting Flask app...
start "HotShort App" /d "%ROOT%" cmd /k ""%VENV_PY%" app.py"

echo Starting ngrok tunnel...
start "HotShort ngrok" /d "%ROOT%" cmd /k "ngrok http %PORT%"

echo Waiting for HotShort app to come online...
for /l %%I in (1,1,20) do (
  powershell -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:%PORT%/health' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
  if not errorlevel 1 goto open_browser
  timeout /t 1 /nobreak >nul
)

echo App did not report healthy in time. Opening browser anyway...

:open_browser
start "" "http://127.0.0.1:%PORT%"
endlocal
