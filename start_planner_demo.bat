@echo off
setlocal
set "ROOT=%~dp0"

if /I "%~1"=="backend" goto backend
if /I "%~1"=="frontend" goto frontend

if not exist "%ROOT%.env" (
  echo Missing .env. Keep your local Goong API key in the ignored .env file.
  pause
  exit /b 1
)
if not exist "%ROOT%frontend\.env.local" (
  echo Missing frontend\.env.local. Keep your local map key there.
  pause
  exit /b 1
)
if not exist "%ROOT%frontend\node_modules\.bin\vite.cmd" (
  echo Frontend dependencies are missing. Run pnpm install in frontend first.
  pause
  exit /b 1
)

start "Station Planner Backend" cmd /k ""%~f0" backend"
start "Station Planner Frontend" cmd /k ""%~f0" frontend"
echo Demo starting. Open http://127.0.0.1:5173
exit /b 0

:backend
cd /d "%ROOT%"
call :configure_proxy
set "CATALOG_STORAGE=memory"
if exist "%ROOT%.venv\Scripts\python.exe" (
  set "PYTHON=%ROOT%.venv\Scripts\python.exe"
) else if exist "D:\Code\open-charge-map\.venv\Scripts\python.exe" (
  set "PYTHON=D:\Code\open-charge-map\.venv\Scripts\python.exe"
) else (
  echo Python environment not found. Create .venv and install backend requirements.
  pause
  exit /b 1
)
"%PYTHON%" -m uvicorn backend.app.main:app --env-file "%ROOT%.env" --host 127.0.0.1 --port 8000
goto done

:frontend
cd /d "%ROOT%frontend"
call :configure_proxy
call node_modules\.bin\vite.cmd --host 127.0.0.1
goto done

:configure_proxy
set "DEMO_PROXY="
for /f "usebackq delims=" %%P in (`powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%detect_proxy.ps1"`) do set "DEMO_PROXY=%%P"
if defined DEMO_PROXY (
  set "HTTP_PROXY=%DEMO_PROXY%"
  set "HTTPS_PROXY=%DEMO_PROXY%"
  set "ALL_PROXY=%DEMO_PROXY%"
  set "http_proxy=%DEMO_PROXY%"
  set "https_proxy=%DEMO_PROXY%"
  set "all_proxy=%DEMO_PROXY%"
  echo Using a reachable machine proxy.
) else (
  set "HTTP_PROXY="
  set "HTTPS_PROXY="
  set "ALL_PROXY="
  set "http_proxy="
  set "https_proxy="
  set "all_proxy="
  echo No reachable proxy found; using direct network.
)
set "NO_PROXY=127.0.0.1,localhost"
set "no_proxy=127.0.0.1,localhost"
goto :eof

:done
endlocal