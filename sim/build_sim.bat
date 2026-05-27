@echo off
setlocal enabledelayedexpansion

REM PyInstaller has to run from the project root: sim_launcher.py, the Images
REM folder, and the sim package all live there. Stash the original directory
REM so popd restores it on exit.
pushd "%~dp0\.."

echo ========================================
echo   OscGoesPurrr Simulator - Build Script
echo ========================================
echo.

REM Reuse the same version-from-Git logic as build.bat so the simulator exe
REM is tagged with the same version as the main app build.
echo Resolving version from Git...
for /f "usebackq tokens=*" %%i in (`python -c "from version import __version__; print(__version__)"`) do set BUILD_VERSION=%%i
echo Building version: !BUILD_VERSION!
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python and try again.
    popd
    pause
    exit /b 1
)

echo [1/4] Checking for PyInstaller...
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo PyInstaller not found. Installing...
    pip install pyinstaller
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

echo [2/4] Installing project dependencies...
REM Simulator only needs a subset of requirements.txt (PySide6, python-osc,
REM zeroconf) but installing the full file is harmless and keeps this script
REM standalone — works even if build.bat was never run.
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [WARNING] Some dependencies may have failed to install. Continuing anyway...
)
echo.

echo [3/4] Building simulator executable with PyInstaller...
echo.

REM Distinct exe name and icon so the simulator shows up as its own entry in
REM Explorer, the taskbar, and Alt-Tab — separate from the main OGP app.
REM The simulator talks pure OSC, so we skip the steamvr_toy_driver payload
REM and --collect-all openvr that the main app needs — keeps the bundle slim.
set SIM_EXE_NAME=OscGoesPurrr_Sim_!BUILD_VERSION!

pyinstaller --noconfirm ^
    --onefile ^
    --windowed ^
    --icon "Images\OGP_Sim_Icon.ico" ^
    --add-data "Images\OGP_Sim_Icon.ico;Images" ^
    --name "!SIM_EXE_NAME!" ^
    sim_launcher.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] PyInstaller build failed!
    echo Temporary files have been preserved for debugging.
    popd
    pause
    exit /b 1
)

echo.
echo [4/4] Cleaning up temporary files...

REM Delete the spec file PyInstaller wrote at the project root.
if exist "!SIM_EXE_NAME!.spec" (
    echo Deleting !SIM_EXE_NAME!.spec...
    del /q "!SIM_EXE_NAME!.spec"
)

REM Delete the build directory (PyInstaller temp files).
if exist "build" (
    echo Deleting build directory...
    rmdir /s /q build
    if %errorlevel% neq 0 (
        echo [WARNING] Failed to delete build directory.
    ) else (
        echo build/ deleted successfully.
    )
)

REM Sweep __pycache__ from project root and immediate subdirectories so
REM source-tree runs aren't polluted with build leftovers.
for /d %%f in (__pycache__) do (
    if exist "%%f" (
        echo Deleting %%f...
        rmdir /s /q "%%f"
    )
)
for /d %%d in (*) do (
    if exist "%%d\__pycache__" (
        echo Deleting %%d\__pycache__...
        rmdir /s /q "%%d\__pycache__"
    )
)

echo.
echo ========================================
echo   Build Complete!
echo ========================================
echo.
echo Executable location: dist\!SIM_EXE_NAME!.exe
echo.

if exist "dist\!SIM_EXE_NAME!.exe" (
    echo [SUCCESS] !SIM_EXE_NAME!.exe created successfully!
) else (
    echo [WARNING] Executable not found in dist folder.
)

echo.
popd
pause
