@echo off
title OscGoesPurrr Test Bench
REM Launches the unified test bench. Runs from the repo root (one level up from
REM this folder) so "python -m testbench" can import the package.
REM Strictly stand-alone — it never imports the main OscGoesPurrr app.

pushd "%~dp0\.."

python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH.
    echo Please install Python from https://www.python.org/
    popd
    pause
    exit /b 1
)

echo Installing/updating test-bench dependencies...
pip install -r "testbench\requirements.txt" >nul 2>&1
if errorlevel 1 (
    echo Warning: Could not install dependencies. Trying to continue anyway...
)

echo Launching OscGoesPurrr Test Bench...
python -m testbench

popd
pause
