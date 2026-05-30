@echo off
title Intiface Toy Simulator
REM Launches the standalone toy simulator. Runs from the repo root (one level
REM up from this folder) so "python -m toysim" can import the package.
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

echo Installing/updating toy-simulator dependencies...
pip install -r "toysim\requirements.txt" >nul 2>&1
if errorlevel 1 (
    echo Warning: Could not install dependencies. Trying to continue anyway...
)

echo Launching Intiface Toy Simulator...
python -m toysim

popd
pause
