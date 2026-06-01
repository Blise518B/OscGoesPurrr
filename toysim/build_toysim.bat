@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   Intiface Toy Simulator - Build Script
echo ========================================
echo.

REM Build from this folder; the package itself lives here and the repo root
REM (one level up) is put on PyInstaller's search path so "import toysim"
REM resolves. The simulator never imports the main OscGoesPurrr app.
pushd "%~dp0"

REM Check Python.
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

echo [2/4] Installing simulator dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [WARNING] Some dependencies may have failed to install. Continuing anyway...
)
echo.

echo [3/4] Building standalone executable with PyInstaller...
echo.
REM --onefile: single .exe   --windowed: no console (PySide6 GUI)
REM --paths "..": repo root on the import path so the toysim package is found
REM __main__.py: the package entry (uses an absolute import, so it freezes fine)
set EXE_NAME=OGP_ToySim
pyinstaller --noconfirm ^
    --onefile ^
    --windowed ^
    --paths ".." ^
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
echo Executable location: toysim\dist\!EXE_NAME!.exe
echo.
if exist "dist\!EXE_NAME!.exe" (
    echo [SUCCESS] !EXE_NAME!.exe created successfully!
) else (
    echo [WARNING] Executable not found in dist folder.
)

popd
echo.
pause
