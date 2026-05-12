@echo off
setlocal
title Building ClassEdge LMS EXE
cd /d "%~dp0"

echo.
echo ================================================================
echo   ClassEdge LMS ^| Build EXE
echo ================================================================
echo.

:: Check venv exists
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: .venv not found.
    echo Run SETUP.bat first to create the virtual environment.
    pause
    exit /b 1
)

:: Install/upgrade PyInstaller
echo [1/3]  Installing PyInstaller...
".venv\Scripts\pip.exe" install --quiet --upgrade pyinstaller
if %errorlevel% neq 0 (
    echo ERROR: Could not install PyInstaller.
    pause
    exit /b 1
)
echo         Done.
echo.

:: Clean previous build artifacts
echo [2/3]  Cleaning previous build...
if exist "dist\ClassEdge LMS.exe" del /f /q "dist\ClassEdge LMS.exe"
if exist "build" rmdir /s /q "build"
if exist "ClassEdge LMS.spec" del /f /q "ClassEdge LMS.spec"
echo         Done.
echo.

:: Build EXE
echo [3/3]  Building EXE (this takes 1-2 minutes)...
echo.
".venv\Scripts\pyinstaller.exe" ^
  --onefile ^
  --windowed ^
  --name "ClassEdge LMS" ^
  --icon "classedge_lms.ico" ^
  --add-data "classedge_lms.ico;." ^
  --add-data "lms_login_setup.py;." ^
  --add-data "lms_start_class.py;." ^
  --add-data "extract_schedule_web.py;." ^
  --add-data "extract_schedule.py;." ^
  --add-data "setup_tasks.py;." ^
  --add-data "create_lesson_folders.py;." ^
  --add-data "upload_lessons.py;." ^
  --hidden-import "tkinter" ^
  --hidden-import "tkinter.scrolledtext" ^
  --hidden-import "tkinter.ttk" ^
  lms_app.py

if %errorlevel% neq 0 (
    echo.
    echo ERROR: PyInstaller build failed.
    echo Check the output above for details.
    pause
    exit /b 1
)

echo.
echo ================================================================
echo   BUILD COMPLETE!
echo.
echo   EXE location:
echo     %~dp0dist\ClassEdge LMS.exe
echo.
echo   Share this single file with co-teachers.
echo   They just double-click it and follow the on-screen steps.
echo.
echo   NOTE: Each teacher must go through First-Time Setup and
echo         Save Login Session with their own Microsoft 365 account.
echo         auth.json is stored on THEIR computer — never shared.
echo ================================================================
echo.
pause
