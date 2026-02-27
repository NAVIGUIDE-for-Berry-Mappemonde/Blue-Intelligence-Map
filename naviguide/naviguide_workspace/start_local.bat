@echo off
:: =============================================================================
:: NAVIGUIDE — Windows Local Development Startup Script (CMD)
:: Starts all 4 services in separate CMD windows:
::   http://localhost:8000   — naviguide-api           (FastAPI + searoute)
::   http://localhost:3008   — naviguide-orchestrator  (LangGraph multi-agent)
::   http://localhost:3010   — naviguide-weather-routing
::   http://localhost:5173   — naviguide-app            (Vite React frontend)
::
:: Usage (from project root OR naviguide_workspace folder):
::   naviguide_workspace\start_local.bat
:: =============================================================================

setlocal enabledelayedexpansion

:: ── Resolve paths ─────────────────────────────────────────────────────────────
:: SCRIPT_DIR = folder containing this .bat (naviguide_workspace\)
set "SCRIPT_DIR=%~dp0"
:: Remove trailing backslash
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

:: PROJECT_ROOT = parent of naviguide_workspace (naviguide-berry-mappemonde\)
for %%I in ("%SCRIPT_DIR%") do set "PROJECT_ROOT=%%~dpI"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

set "API_DIR=%PROJECT_ROOT%\naviguide-api"
set "FRONT_DIR=%PROJECT_ROOT%\naviguide-app"
set "LOG_DIR=%PROJECT_ROOT%\logs"

echo.
echo  =================================================
echo    NAVIGUIDE — Windows Startup
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
        if not "%%a"=="" (
            taskkill /F /PID %%a >nul 2>&1
        )
    )
)
echo [OK] Ports cleared.

:: ── Verify Python ─────────────────────────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo [X] Python not found!
    echo     Download: https://www.python.org/downloads/
    echo     Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo [OK] %%v

:: ── Verify Node.js ────────────────────────────────────────────────────────────
where node >nul 2>&1
if errorlevel 1 (
    echo [X] Node.js not found!
    echo     Download: https://nodejs.org/
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('node --version 2^>^&1') do echo [OK] Node %%v

:: ── Install Python dependencies ───────────────────────────────────────────────
echo.
echo [*] Installing Python dependencies (first run may take 1-2 min)...
python -m pip install -q -r "%API_DIR%\requirements.txt" --user
python -m pip install -q -r "%SCRIPT_DIR%\requirements.txt" --user
echo [OK] Python dependencies ready.

:: ── Install npm dependencies ──────────────────────────────────────────────────
if not exist "%FRONT_DIR%\node_modules" (
    echo [*] Installing npm packages (first run)...
    cd /d "%FRONT_DIR%" && npm install --silent
    cd /d "%SCRIPT_DIR%"
)
echo [OK] npm packages ready.

:: ── Create .env for naviguide-api ─────────────────────────────────────────────
if not exist "%API_DIR%\.env" (
    echo COPERNICUS_USERNAME=berrymappemonde@gmail.com>  "%API_DIR%\.env"
    echo COPERNICUS_PASSWORD=Hackmyroute2027>>             "%API_DIR%\.env"
    echo PORT=8000>>                                       "%API_DIR%\.env"
    echo [OK] Created naviguide-api\.env
)

:: ── Create .env.local for Vite frontend ───────────────────────────────────────
echo VITE_API_URL=http://localhost:8000>  "%FRONT_DIR%\.env.local"
echo VITE_ORCHESTRATOR_URL=http://localhost:3008>> "%FRONT_DIR%\.env.local"
echo VITE_WEATHER_ROUTING_URL=http://localhost:3010>> "%FRONT_DIR%\.env.local"
echo [OK] Created naviguide-app\.env.local

echo.
echo [*] Launching services in separate windows...

:: ── Service 1: naviguide-api (port 8000) ──────────────────────────────────────
start "NAVIGUIDE-API [port 8000]" cmd /k "cd /d "%API_DIR%" && echo Starting naviguide-api... && python main.py"

:: ── Service 2: Orchestrator (port 3008) ───────────────────────────────────────
start "NAVIGUIDE-ORCHESTRATOR [port 3008]" cmd /k "cd /d "%SCRIPT_DIR%" && echo Starting orchestrator... && set PORT=3008 && python -m naviguide_orchestrator.main"

:: ── Service 3: Weather Routing (port 3010) ────────────────────────────────────
start "NAVIGUIDE-WEATHER [port 3010]" cmd /k "cd /d "%SCRIPT_DIR%" && echo Starting weather-routing... && set PORT=3010 && python -m naviguide_weather_routing.main"

echo [OK] 3 backend services launching...

:: ── Wait for backends ─────────────────────────────────────────────────────────
echo [*] Waiting 20s for backends to initialise...
timeout /T 20 /NOBREAK >nul

:: ── Service 4: Frontend (Vite - port 5173) ────────────────────────────────────
start "NAVIGUIDE-FRONTEND [port 5173]" cmd /k "cd /d "%FRONT_DIR%" && echo Starting Vite frontend... && npm run dev -- --host"

echo [OK] Frontend launching...
timeout /T 5 /NOBREAK >nul

:: ── Done ──────────────────────────────────────────────────────────────────────
echo.
echo  =================================================
echo    NAVIGUIDE is running locally on Windows!
echo  =================================================
echo    Frontend :         http://localhost:5173
echo    API :              http://localhost:8000
echo    Orchestrator :     http://localhost:3008
echo    Weather Routing :  http://localhost:3010
echo  =================================================
echo.
echo  4 terminal windows are open - one per service.
echo  If a service fails, check that window for errors.
echo.
echo  IMPORTANT - Clear browser cache on first run:
echo    Open http://localhost:5173 -^> Press F12 -^> Console, run:
echo    localStorage.removeItem('naviguide_expedition_plan_v1')
echo    Then refresh the page (Ctrl+R)
echo.
echo  To stop all services: run stop_local.bat
echo  =================================================
echo.
pause
endlocal
