@echo off
setlocal enabledelayedexpansion
title ClassEdge LMS — Update Schedule
cd /d "%~dp0"

echo.
echo ================================================================
echo   ClassEdge LMS ^| Auto Start Class ^| UPDATE SCHEDULE
echo ================================================================
echo.

:: Check that setup was already done
if not exist ".venv\Scripts\python.exe" (
    echo  ERROR: Setup has not been completed yet.
    echo  Please run SETUP.bat first.
    echo.
    pause
    exit /b 1
)

if not exist "auth.json" (
    echo  ERROR: auth.json not found — your login session is missing.
    echo  Please run SETUP.bat first (or re-run the login step).
    echo.
    pause
    exit /b 1
)

:: ---------------------------------------------------------------
:: STEP 1 — Re-scrape schedule from ClassEdge
:: ---------------------------------------------------------------
echo [1/2]  Reading updated schedule from ClassEdge...
".venv\Scripts\python.exe" extract_schedule_web.py
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Could not read schedule from ClassEdge.
    echo  If your session expired, re-run SETUP.bat to log in again.
    pause
    exit /b 1
)
echo.

:: ---------------------------------------------------------------
:: STEP 2 — Re-register tasks in Task Scheduler
:: ---------------------------------------------------------------
echo [2/2]  Re-registering classes in Windows Task Scheduler...
".venv\Scripts\python.exe" setup_tasks.py
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Task registration failed.
    pause
    exit /b 1
)

echo.
echo ================================================================
echo   UPDATE COMPLETE!
echo.
echo   Your Task Scheduler has been updated with the latest
echo   class schedule from ClassEdge.
echo ================================================================
echo.
pause
