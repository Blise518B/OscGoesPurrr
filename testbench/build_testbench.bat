@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   OscGoesPurrr Test Bench - Build Script
echo ========================================
echo.

REM Build from this folder; the package lives here and the repo root (one level
REM up) goes on PyInstaller's search path so "import testbench" resolves. The
REM bench never imports the main OscGoesPurrr app.
pushd "%~dp0"

REM Resolve a Python launcher (prefer the 'py' launcher over the Microsoft
REM Store 'python' stub) and build / validate the test-bench venv (.venv in
REM testbench\). pip / PyInstaller all run through the venv.
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo [ERROR] Python not found. Install Python 3.10+ from https://www.python.org/
    popd
    pause
    exit /b 1
)

set "VENV_PY=.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import sys" >nul 2>&1 || (
        echo Existing virtual environment is broken; recreating...
        rmdir /s /q ".venv"
    )
)
if not exist "%VENV_PY%" (
    if exist ".venv" rmdir /s /q ".venv"
    echo Creating test-bench virtual environment...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create virtual environment.
        popd
        pause
        exit /b 1
    )
)

echo [1/4] Checking for PyInstaller...
"%VENV_PY%" -m pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo PyInstaller not found. Installing...
    "%VENV_PY%" -m pip install pyinstaller
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install PyInstaller.
        popd
        pause
        exit /b 1
    )
) else (
    echo PyInstaller already installed.
)
echo.

echo [2/4] Installing test-bench dependencies...
"%VENV_PY%" -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [WARNING] Some dependencies may have failed to install. Continuing anyway...
)
echo.

echo [3/4] Building standalone executable with PyInstaller...
echo.
REM --onefile: single .exe   --windowed: no console (PySide6 GUI)
REM --paths "..": repo root on the import path so "import testbench" resolves
REM --collect-all pyqtgraph: pyqtgraph loads parts dynamically; without this
REM   PyInstaller misses them and the plots blow up at runtime
REM __main__.py: the package entry (absolute import, freezes fine)
set EXE_NAME=OGP_TestBench

REM Bundle the sim icon if it's present at the repo root (optional — the bench
REM falls back to a default icon when it's missing).
set ICON_OPTS=
if exist "..\Images\OGP_Sim_Icon.ico" set ICON_OPTS=--icon "..\Images\OGP_Sim_Icon.ico" --add-data "..\Images\OGP_Sim_Icon.ico;Images"

"%VENV_PY%" -m PyInstaller --noconfirm ^
    --onefile ^
    --windowed ^
    --paths ".." ^
    --collect-all pyqtgraph ^
    !ICON_OPTS! ^
    --name "!EXE_NAME!" ^
    "__main__.py"

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] PyInstaller build failed!
    popd
    pause
    exit /b 1
)

echo.
echo [4/4] Cleaning up temporary files...
for %%f in (*.spec) do (
    if exist "%%f" del /q "%%f"
)
if exist "build" rmdir /s /q build
if exist "__pycache__" rmdir /s /q __pycache__

echo.
echo ========================================
echo   Build Complete!
echo ========================================
echo.
echo Executable location: testbench\dist\!EXE_NAME!.exe
echo.
if exist "dist\!EXE_NAME!.exe" (
    echo [SUCCESS] !EXE_NAME!.exe created successfully!
) else (
    echo [WARNING] Executable not found in dist folder.
)

popd
echo.
pause
