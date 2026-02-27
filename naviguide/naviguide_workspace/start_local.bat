@echo off
:: =============================================================================
:: NAVIGUIDE — Windows Local Development Startup Script (CMD)
:: Fixed: removed && inside if-blocks, use /D for start working directory
::
:: Services started:
::   http://localhost:8000   — naviguide-api
::   http://localhost:3008   — naviguide-orchestrator (Agent1 + Agent3)
::   http://localhost:3010   — naviguide-weather-routing
::   http://localhost:5173   — naviguide-app (Vite React)
::
:: Usage: naviguide_workspace\start_local.bat
:: =============================================================================

setlocal enabledelayedexpansion

:: ── Resolve SCRIPT_DIR (naviguide_workspace\) ─────────────────────────────────
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

:: ── Resolve PROJECT_ROOT (parent folder) ─────────────────────────────────────
for %%I in ("%SCRIPT_DIR%") do set "PROJECT_ROOT=%%~dpI"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

set "API_DIR=%PROJECT_ROOT%\naviguide-api"
set "FRONT_DIR=%PROJECT_ROOT%\naviguide-app"
set "LOG_DIR=%PROJECT_ROOT%\logs"

echo.
echo  =================================================
echo    NAVIGUIDE - Windows Startup
echo  =================================================
echo    Project root : %PROJECT_ROOT%
echo    Logs folder  : %LOG_DIR%
echo  =================================================
echo.

:: ── Create logs folder ────────────────────────────────────────────────────────
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

:: ── Free ports 8000, 3008, 3010, 5173 ────────────────────────────────────────
echo [*] Freeing ports 8000, 3008, 3010, 5173...
for %%P in (8000 3008 3010 5173) do (
    for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":%%P "') do (
        if not "%%a"=="" taskkill /F /PID %%a >nul 2>&1
    )
)
echo [OK] Ports cleared.

:: ── Verify Python ─────────────────────────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo [X] Python not found. Download: https://www.python.org/downloads/
    pause
    exit /b 1
)
python --version

:: ── Verify Node.js ────────────────────────────────────────────────────────────
where node >nul 2>&1
if errorlevel 1 (
    echo [X] Node.js not found. Download: https://nodejs.org/
    pause
    exit /b 1
)
node --version

:: ── Install Python dependencies ───────────────────────────────────────────────
echo.
echo [*] Installing Python dependencies...
python -m pip install -q -r "%API_DIR%\requirements.txt" --user
python -m pip install -q -r "%SCRIPT_DIR%\requirements.txt" --user
echo [OK] Python dependencies ready.

:: ── Install npm dependencies (pushd/popd avoids && inside if block) ───────────
if not exist "%FRONT_DIR%\node_modules" (
    echo [*] Installing npm packages, please wait...
    pushd "%FRONT_DIR%"
    call npm install --silent
    popd
)
echo [OK] npm packages ready.

:: ── Create .env for naviguide-api ─────────────────────────────────────────────
if not exist "%API_DIR%\.env" (
    echo COPERNICUS_USERNAME=berrymappemonde@gmail.com>"%API_DIR%\.env"
    echo COPERNICUS_PASSWORD=Hackmyroute2027>>"%API_DIR%\.env"
    echo PORT=8000>>"%API_DIR%\.env"
    echo [OK] Created naviguide-api\.env
)

:: ── Create .env.local for Vite frontend ───────────────────────────────────────
echo VITE_API_URL=http://localhost:8000>"%FRONT_DIR%\.env.local"
echo VITE_ORCHESTRATOR_URL=http://localhost:3008>>"%FRONT_DIR%\.env.local"
echo VITE_WEATHER_ROUTING_URL=http://localhost:3010>>"%FRONT_DIR%\.env.local"
echo [OK] Created naviguide-app\.env.local

echo.
echo [*] Launching 4 services in separate windows...

:: ── Service 1: naviguide-api (port 8000) ──────────────────────────────────────
:: Use /D to set working directory — avoids nested-quote issue
start "NAVIGUIDE-API [8000]" /D "%API_DIR%" cmd /k "python main.py"

:: ── Service 2: Orchestrator (port 3008) ───────────────────────────────────────
start "NAVIGUIDE-ORCH [3008]" /D "%SCRIPT_DIR%" cmd /k "set PORT=3008 && python -m naviguide_orchestrator.main"

:: ── Service 3: Weather Routing (port 3010) ────────────────────────────────────
start "NAVIGUIDE-WEATHER [3010]" /D "%SCRIPT_DIR%" cmd /k "set PORT=3010 && python -m naviguide_weather_routing.main"

echo [OK] 3 backend services launching in separate windows...

:: ── Wait for backends to boot ─────────────────────────────────────────────────
echo [*] Waiting 20s for backends to initialise...
timeout /T 20 /NOBREAK >nul

:: ── Service 4: Frontend (Vite - port 3009) ────────────────────────────────────
start "NAVIGUIDE-FRONTEND [3009]" /D "%FRONT_DIR%" cmd /k "npm run dev -- --host"

echo [OK] Frontend launching...
timeout /T 5 /NOBREAK >nul

:: ── Done ──────────────────────────────────────────────────────────────────────
echo.
echo  =================================================
echo    NAVIGUIDE is running locally on Windows!
echo  =================================================
echo    Frontend :        http://localhost:3009   ^<-- open this
echo    API :             http://localhost:8000
echo    Orchestrator :    http://localhost:3008
echo    Weather Routing : http://localhost:3010
echo  =================================================
echo.
echo  4 windows are open - one per service.
echo  If a service fails, check that window for the error.
echo.
echo  CLEAR BROWSER CACHE on first run:
echo    Open http://localhost:5173 then press F12
echo    Go to Console tab and run:
echo    localStorage.removeItem('naviguide_expedition_plan_v1')
echo    Then press Ctrl+R
echo.
echo  To stop: run naviguide_workspace\stop_local.bat
echo  NOTE: Use port 3009 only. Port 5173 is NOT used.
echo  =================================================
echo.
pause
endlocal
