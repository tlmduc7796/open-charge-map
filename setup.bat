@echo off
rem ============================================================================
rem Smart EV Journey - one-time setup.
rem Installs backend/frontend dependencies and bootstraps PostgreSQL (Docker).
rem Safe to re-run: finished steps are skipped.
rem Usage: setup.bat [nopause]
rem ============================================================================
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo ==== Smart EV Journey - setup ====

echo.
echo [1/5] Checking prerequisites...
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH. Install Python 3.12.
    goto fail
)
python -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 12) else 1)"
if errorlevel 1 (
    echo [ERROR] Python 3.12 or newer is required.
    goto fail
)
where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found in PATH. Install Node.js 20.19+ or 22.12+.
    goto fail
)
where docker >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker not found in PATH. Install Docker Desktop.
    goto fail
)
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker Desktop is not running. Start it and run setup.bat again.
    goto fail
)
where pnpm >nul 2>&1
if errorlevel 1 (
    echo pnpm not found, installing pnpm@11.19.0 globally...
    call npm install --global pnpm@11.19.0
    where pnpm >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] pnpm was installed but is not on PATH yet. Reopen the terminal and run setup.bat again.
        goto fail
    )
)

echo.
echo [2/5] Environment files...
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo Created .env from .env.example - set GOONG_API_KEY there for live routing and places.
) else (
    echo .env already exists, kept.
)
if not exist "frontend\.env.local" (
    copy "frontend\.env.example" "frontend\.env.local" >nul
    echo Created frontend\.env.local - set VITE_GOONG_MAPTILES_KEY there for Goong map tiles.
) else (
    echo frontend\.env.local already exists, kept.
)

echo.
echo [3/5] Backend dependencies (.venv)...
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 goto fail
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -r backend\requirements-dev.txt
if errorlevel 1 goto fail

echo.
echo [4/5] Frontend dependencies (pnpm)...
call pnpm --dir frontend install --frozen-lockfile
if errorlevel 1 goto fail

echo.
echo [5/5] PostgreSQL/PostGIS database...
pushd database
echo.
docker compose up -d postgres
if errorlevel 1 goto fail_popd

set /a tries=0
:wait_pg
docker compose exec -T postgres pg_isready -U smart_ev -d postgres >nul 2>&1
if not errorlevel 1 goto pg_ready
set /a tries+=1
if %tries% geq 60 (
    echo [ERROR] PostgreSQL did not become ready within 60 seconds.
    goto fail_popd
)
timeout /t 1 /nobreak >nul
goto wait_pg

:pg_ready
rem bootstrap_database.py refuses a database that already holds rows, so skip it then.
set "STATIONS=0"
for /f "usebackq delims=" %%i in (`docker compose exec -T postgres psql -U smart_ev -d smart_ev_data -tAc "SELECT count(*) FROM stations" 2^>nul`) do set "STATIONS=%%i"
if not "%STATIONS%"=="0" (
    echo Database already populated with %STATIONS% stations, skipping bootstrap.
) else (
    "..\.venv\Scripts\python.exe" scripts\bootstrap_database.py
    if errorlevel 1 goto fail_popd
)
popd

echo.
echo ==== Setup complete. Run start.bat to launch the app. ====
goto done

:fail_popd
popd
:fail
echo.
echo ==== Setup FAILED - see messages above. ====
endlocal
if /i not "%~1"=="nopause" pause
exit /b 1

:done
endlocal
if /i not "%~1"=="nopause" pause
exit /b 0
