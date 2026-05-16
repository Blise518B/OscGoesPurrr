@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   OscGoesPurrr - PyInstaller Build Script
echo ========================================
echo.

REM Get version from version.py by querying git commit count
echo Resolving version from Git...
for /f "usebackq tokens=*" %%i in (`python -c "from version import __version__; print(__version__)"`) do set BUILD_VERSION=%%i
echo Building version: !BUILD_VERSION!
echo.

REM Check if Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python and try again.
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
        pause
        exit /b 1
    )
) else (
    echo PyInstaller already installed.
)
echo.

echo [2/4] Installing project dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [WARNING] Some dependencies may have failed to install. Continuing anyway...
)
echo.

echo [3/4] Building standalone executable with PyInstaller...
echo.

REM Run PyInstaller (no --clean flag for faster rebuilds)
REM --onefile: bundle everything into a single executable
REM --windowed: no console window (GUI app with customtkinter)
REM --name: output executable name
REM PyInstaller automatically analyzes imports, so all .py modules are bundled
REM Temp files are cleaned up after successful build in step 4
pyinstaller --noconfirm ^
    --onefile ^
    --windowed ^
    --name "OscGoesPurrr" ^
    --version-number !BUILD_VERSION! ^
    main.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] PyInstaller build failed!
    echo Temporary files have been preserved for debugging.
    pause
    exit /b 1
)

echo.
echo [4/4] Cleaning up temporary files...

REM Delete the build directory (PyInstaller temp files)
if exist "build" (
    echo Deleting build directory...
    rmdir /s /q build
    if %errorlevel% neq 0 (
        echo [WARNING] Failed to delete build directory.
    ) else (
        echo build/ deleted successfully.
    )
)

REM Delete the __pycache__ directories
for /d %%f in (__pycache__) do (
    if exist "%%f" (
        echo Deleting %%f...
        rmdir /s /q "%%f"
    )
)

REM Delete Python cache in subdirectories
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
echo Executable location: dist\OscGoesPurrr.exe
echo.

REM Check if the exe was created
if exist "dist\OscGoesPurrr.exe" (
    echo [SUCCESS] OscGoesPurrr.exe created successfully!
) else (
    echo [WARNING] Executable not found in dist folder.
)

echo.
pause