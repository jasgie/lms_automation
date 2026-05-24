@echo off
setlocal
title Building ClassEdge LMS — SNCFI Edition
cd /d "%~dp0"

echo.
echo ================================================================
echo   ClassEdge LMS ^| Build EXE  (SNCFI Edition)
echo ================================================================
echo.

:: Locate venv
set "VENV_DIR=%~dp0.venv"
if not exist "%VENV_DIR%\Scripts\python.exe" (
    set "VENV_DIR=%LOCALAPPDATA%\ClassEdge LMS\.venv"
)
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo ERROR: Virtual environment not found.
    echo Run SETUP.bat first.
    pause
    exit /b 1
)
echo Using venv: %VENV_DIR%
echo.

:: Install/upgrade PyInstaller
echo [1/4]  Installing PyInstaller...
"%VENV_DIR%\Scripts\pip.exe" install --quiet --upgrade pyinstaller
if %errorlevel% neq 0 (
    echo ERROR: Could not install PyInstaller.
    pause
    exit /b 1
)
echo         Done.
echo.

:: Patch source files for SNCFI
echo [2/4]  Patching source for SNCFI...
"%VENV_DIR%\Scripts\python.exe" "%~dp0_patch_sncfi.py"
if %errorlevel% neq 0 (
    echo ERROR: Patch script failed.
    pause
    exit /b 1
)
echo         Done.
echo.

:: Clean previous SNCFI build artifacts
echo [3/4]  Cleaning previous SNCFI build...
if exist "dist\ClassEdge LMS - SNCFI.exe" del /f /q "dist\ClassEdge LMS - SNCFI.exe"
if exist "build" rmdir /s /q "build"
if exist "ClassEdge LMS - SNCFI.spec" del /f /q "ClassEdge LMS - SNCFI.spec"
echo         Done.
echo.

:: Build EXE
echo [4/4]  Building SNCFI EXE (this takes 1-2 minutes)...
echo.
"%VENV_DIR%\Scripts\pyinstaller.exe" ^
  --onefile ^
  --windowed ^
  --name "ClassEdge LMS - SNCFI" ^
  --icon "classedge_lms.ico" ^
  --add-data "classedge_lms.ico;." ^
  --add-data "lms_login_setup.py;." ^
  --add-data "lms_start_class.py;." ^
  --add-data "_sncfi_tmp\extract_schedule_web.py;." ^
  --add-data "extract_schedule.py;." ^
  --add-data "setup_tasks.py;." ^
  --add-data "create_lesson_folders.py;." ^
  --add-data "upload_lessons.py;." ^
  --hidden-import "tkinter" ^
  --hidden-import "tkinter.scrolledtext" ^
  --hidden-import "tkinter.ttk" ^
  _lms_app_sncfi.py

set BUILD_ERR=%errorlevel%

:: Restore — always clean up temp files
del /f /q "_lms_app_sncfi.py" 2>nul
if exist "_sncfi_tmp" rmdir /s /q "_sncfi_tmp" 2>nul

if %BUILD_ERR% neq 0 (
    echo.
    echo ERROR: PyInstaller build failed.
    echo Check the output above for details.
    pause
    exit /b 1
)

echo.
echo ================================================================
echo   BUILD COMPLETE!  (SNCFI Edition)
echo.
echo   EXE location:
echo     %~dp0dist\ClassEdge LMS - SNCFI.exe
echo.
echo   Distribute this EXE to SNCFI teachers.
echo   Each teacher must run First-Time Setup and Save Login Session
echo   with their own Microsoft 365 account.
echo ================================================================
echo.
pause
