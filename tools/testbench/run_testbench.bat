@echo off
title OscGoesPurrr Test Bench
setlocal
REM Launches the unified test bench from the repo root (one level up) so
REM "python -m testbench" can import the package. Strictly stand-alone — it
REM never imports the main OscGoesPurrr app, so it uses its OWN venv
REM (testbench\.venv), separate from the main app's venv.

set "TBROOT=%~dp0"
set "VENV_PY=%TBROOT%.venv\Scripts\python.exe"

REM Prefer the 'py' launcher (a real python.org install) over bare 'python'
REM (often the Microsoft Store stub that builds broken venvs).
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo Error: Python is not installed or not on PATH.
    echo Please install Python 3.10+ from https://www.python.org/
    pause
    exit /b 1
)

REM Validate / (re)create the test-bench venv (missing or broken).
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import sys" >nul 2>&1 || (
        echo Existing virtual environment is broken; recreating...
        rmdir /s /q "%TBROOT%.venv"
    )
)
if not exist "%VENV_PY%" (
    if exist "%TBROOT%.venv" rmdir /s /q "%TBROOT%.venv"
    echo Creating test-bench virtual environment...
    %PY% -m venv "%TBROOT%.venv"
    if errorlevel 1 (
        echo Error: Could not create virtual environment.
        pause
        exit /b 1
    )
)

echo Installing/updating test-bench dependencies...
"%VENV_PY%" -m pip install -r "%TBROOT%requirements.txt"
if errorlevel 1 (
    echo Warning: Could not install dependencies. Trying to continue anyway...
)

echo Launching OscGoesPurrr Test Bench...
pushd "%TBROOT%.."
"%VENV_PY%" -m testbench
popd

pause
