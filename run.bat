@echo off
title OscGoesPurrr
setlocal

:: Change to script directory so relative paths work no matter where the
:: .bat is launched from.
cd /d "%~dp0"

:: ------------------------------------------------------------------
:: Resolve a Python launcher. Prefer the 'py' launcher (a real
:: python.org install) over bare 'python', which on Windows is often the
:: Microsoft Store stub that builds venvs whose python.exe can't spawn a
:: child process.
:: ------------------------------------------------------------------
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

echo Starting OscGoesPurrr...
echo.

:: ------------------------------------------------------------------
:: Validate the venv, (re)creating it if missing or broken. A venv
:: breaks if the Python it was built from is uninstalled/upgraded, or if
:: the venv folder was copied/moved (venvs aren't relocatable).
:: ------------------------------------------------------------------
set "VENV_PY=venv\Scripts\python.exe"
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import sys" >nul 2>&1 || (
        echo Existing virtual environment is broken; recreating...
        rmdir /s /q "venv"
    )
)
if not exist "%VENV_PY%" (
    if exist "venv" rmdir /s /q "venv"
    echo Creating virtual environment...
    %PY% -m venv venv
    if errorlevel 1 (
        echo Error: Could not create virtual environment.
        pause
        exit /b 1
    )
)

:: Install/update dependencies into the venv (not system Python).
echo Installing/updating dependencies...
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Warning: Could not install dependencies. Trying to continue anyway...
    echo.
)

:: Run the application from the venv.
echo Launching OscGoesPurrr...
"%VENV_PY%" main.py

pause
