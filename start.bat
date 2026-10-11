@echo off
rem ============================================================================
rem Smart EV Journey - start database, backend and frontend.
rem Run setup.bat once before using this file.
rem Close the two opened windows (or press Ctrl+C in them) to stop the app.
rem ============================================================================
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo ==== Smart EV Journey - start ====

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Backend .venv is missing. Run setup.bat first.
    goto fail
)
if not exist "frontend\node_modules" (
    echo [ERROR] Frontend dependencies are missing. Run setup.bat first.
    goto fail
)
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker Desktop is not running. Start it and run start.bat again.
    goto fail
)

echo.
echo Starting PostgreSQL...
echo (a freshly started container wipes its volume and reloads the schema, seed data and the
echo  30-day simulator history; this takes a few seconds)
pushd database
docker compose up -d --wait postgres
if errorlevel 1 (
    popd
    echo [ERROR] PostgreSQL failed to start or load its data. See: docker compose logs postgres
    goto fail
)
popd

echo Starting backend  - http://127.0.0.1:8000
start "SmartEV Backend" cmd /k ".venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000"

echo Starting frontend - http://127.0.0.1:5173
start "SmartEV Frontend" cmd /k "pnpm --dir frontend dev --host 127.0.0.1"

echo Waiting for backend health check...
set /a tries=0
:wait_api
curl -s -f -o nul http://127.0.0.1:8000/health
if not errorlevel 1 goto api_ready
set /a tries+=1
if %tries% geq 60 (
    echo Backend not healthy after 60 seconds - check the SmartEV Backend window.
    goto open_browser
)
timeout /t 1 /nobreak >nul
goto wait_api

:api_ready
echo Backend is healthy.

:open_browser
start "" http://127.0.0.1:5173

echo.
echo App:      http://127.0.0.1:5173
echo API docs: http://127.0.0.1:8000/docs
endlocal
exit /b 0

:fail
echo.
echo ==== Start FAILED - see messages above. ====
endlocal
if /i not "%~1"=="nopause" pause
exit /b 1
