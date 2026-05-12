@echo off
setlocal enabledelayedexpansion
title ClassEdge LMS — Upload Lessons
cd /d "%~dp0"

echo.
echo ================================================================
echo   ClassEdge LMS ^| Bulk Lesson Uploader
echo ================================================================
echo.

:: Check setup was done
if not exist ".venv\Scripts\python.exe" (
    echo  ERROR: Setup not complete. Run SETUP.bat first.
    echo.
    pause
    exit /b 1
)

if not exist "auth.json" (
    echo  ERROR: Login session not found.
    echo  Run SETUP.bat first to save your Microsoft 365 session.
    echo.
    pause
    exit /b 1
)

:: Create lesson folders if they don't exist yet
if not exist "lessons\" (
    echo  Creating subject lesson folders for the first time...
    echo.
    ".venv\Scripts\python.exe" create_lesson_folders.py
    echo.
    echo ================================================================
    echo   Lesson folders created!
    echo.
    echo   NEXT STEPS:
    echo   1. Open the "lessons\" folder (it is next to this .bat file)
    echo   2. Drop your lesson files into the matching subject folder
    echo      e.g.:  lessons\Web Design (LEC)\01 - HTML Basics.pdf
    echo   3. Run this file again to upload them to ClassEdge
    echo ================================================================
    echo.
    pause
    exit /b 0
)

:: Ask which term
echo  Which term are you uploading lessons for?
echo.
echo   [1] Midterm
echo   [2] Final Term
echo   [3] Auto-detect (use whatever is currently selected on ClassEdge)
echo.
set /p TERM_CHOICE=  Enter 1, 2, or 3 (default: 3):  

if "%TERM_CHOICE%"=="1" (
    set TERM_ARG=--term midterm
    set TERM_LABEL=Midterm
) else if "%TERM_CHOICE%"=="2" (
    set TERM_ARG=--term final
    set TERM_LABEL=Final Term
) else (
    set TERM_ARG=--term auto
    set TERM_LABEL=Auto-detect
)

echo.
echo  Term selected: %TERM_LABEL%
echo  Scanning lesson folders for new files...
echo.

".venv\Scripts\python.exe" upload_lessons.py %TERM_ARG%

echo.
echo ================================================================
echo   Done! Check upload_lessons.log for a full report.
echo   If any uploads failed, check the errors\ folder for screenshots.
echo ================================================================
echo.
pause
