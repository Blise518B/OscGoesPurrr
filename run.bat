@echo off
title OscGoesPurrr

:: Change to script directory
cd /d "%~dp0"

:: Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH.
    echo Please install Python from https://www.python.org/
    pause
    exit /b 1
)

echo Starting OscGoesPurrr...
echo.

:: Install/update dependencies
echo Installing/updating dependencies...
pip install -r requirements.txt >nul 2>&1
if errorlevel 1 (
    echo Warning: Could not install dependencies. Trying to continue anyway...
    echo.
)

:: Run the application
echo Launching OscGoesPurrr...
python main.py

pause