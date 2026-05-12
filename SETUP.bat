@echo off
setlocal enabledelayedexpansion
title ClassEdge LMS — First-Time Setup
cd /d "%~dp0"

echo.
echo ================================================================
echo   ClassEdge LMS ^| Auto Start Class ^| FIRST-TIME SETUP
echo ================================================================
echo.

:: ---------------------------------------------------------------
:: STEP 1 — Check Python
:: ---------------------------------------------------------------
echo [1/6]  Checking for Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Python is not installed or not in PATH.
    echo.
    echo  Please install Python 3.10+ from:
    echo    https://www.python.org/downloads/
    echo.
    echo  IMPORTANT: During install, tick "Add Python to PATH".
    echo  Then close and re-open this file.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo         Found: %%v
echo.

:: ---------------------------------------------------------------
:: STEP 2 — Create virtual environment
:: ---------------------------------------------------------------
echo [2/6]  Setting up virtual environment...
if exist ".venv\Scripts\python.exe" (
    echo         Already exists, skipping.
) else (
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo  ERROR: Could not create virtual environment.
        pause
        exit /b 1
    )
    echo         Created .venv successfully.
)
echo.

:: ---------------------------------------------------------------
:: STEP 3 — Install Python packages
:: ---------------------------------------------------------------
echo [3/6]  Installing Python packages (playwright, python-docx)...
".venv\Scripts\pip.exe" install --quiet --upgrade playwright python-docx
if %errorlevel% neq 0 (
    echo  ERROR: pip install failed. Check your internet connection.
    pause
    exit /b 1
)
echo         Packages installed.
echo.

:: ---------------------------------------------------------------
:: STEP 4 — Install Playwright Chromium
:: ---------------------------------------------------------------
echo [4/6]  Installing Playwright Chromium browser...
".venv\Scripts\playwright.exe" install chromium
if %errorlevel% neq 0 (
    echo  ERROR: Playwright browser install failed.
    pause
    exit /b 1
)
echo.

:: ---------------------------------------------------------------
:: STEP 5 — Save Microsoft 365 login session
:: ---------------------------------------------------------------
echo [5/6]  Saving your Microsoft 365 login session...
echo.
echo  ╔═══════════════════════════════════════════════════════╗
echo  ║  ACTION REQUIRED — Please do the following:           ║
echo  ║                                                       ║
echo  ║  1. A browser window is about to open.                ║
echo  ║  2. Log in with your HCCI Microsoft 365 account.      ║
echo  ║  3. Complete MFA (if prompted).                       ║
echo  ║  4. Wait until you see your ClassEdge dashboard.      ║
echo  ║  5. Come back HERE and press Enter.                   ║
echo  ╚═══════════════════════════════════════════════════════╝
echo.
pause

".venv\Scripts\python.exe" lms_login_setup.py
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Login setup failed. Please try again.
    pause
    exit /b 1
)
echo.

:: ---------------------------------------------------------------
:: STEP 6 — Extract schedule + register tasks
:: ---------------------------------------------------------------
echo [6/6]  Reading your class schedule from ClassEdge...
".venv\Scripts\python.exe" extract_schedule_web.py
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Could not read your schedule from ClassEdge.
    echo  Make sure you completed the login step above.
    pause
    exit /b 1
)
echo.

echo         Registering classes in Windows Task Scheduler...
".venv\Scripts\python.exe" setup_tasks.py
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Task registration failed.
    pause
    exit /b 1
)

:: ---------------------------------------------------------------
:: DONE
:: ---------------------------------------------------------------
echo.
echo ================================================================
echo   SETUP COMPLETE!
echo.
echo   Your classes are now registered in Windows Task Scheduler.
echo   15 minutes before each class, "Start Class" will be clicked
echo   automatically — even if your laptop was off at trigger time.
echo.
echo   NOTHING ELSE NEEDED.  Just open your laptop before class!
echo ================================================================
echo.
echo  To update your schedule next semester, run:  UPDATE.bat
echo.
pause
