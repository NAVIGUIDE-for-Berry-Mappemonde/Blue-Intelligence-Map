@echo off
:: =============================================================================
:: NAVIGUIDE — Windows Stop Script (CMD)
:: Kills all 4 services by freeing ports 8000, 3008, 3010, 5173
::
:: Usage: naviguide_workspace\stop_local.bat
:: =============================================================================

echo.
echo [NAVIGUIDE] Stopping all services...
echo.

for %%P in (8000 3008 3010 5173) do (
    set "found="
    for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":%%P "') do (
        if not "%%a"=="" (
            taskkill /F /PID %%a >nul 2>&1
            if not errorlevel 1 (
                echo [OK] Stopped service on port %%P ^(PID %%a^)
                set "found=1"
            )
        )
    )
    if not defined found echo [--] Nothing running on port %%P
)

echo.
echo [NAVIGUIDE] All services stopped.
echo.
pause
