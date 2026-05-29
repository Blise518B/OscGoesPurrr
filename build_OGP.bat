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

REM Bake the resolved version into _version_baked.py so the frozen exe does
REM not shell out to git at startup. Each subprocess.run from a --windowed
REM build pops a brief console window per call, which is what we are avoiding.
REM repr() handles any special characters in the branch suffix safely.
echo Baking version into _version_baked.py...
python -c "from version import __version__ as v, _SHORT_HASH as h; open('_version_baked.py','w',encoding='utf-8').write('VERSION = ' + repr(v) + '\nSHORT_HASH = ' + repr(h) + '\n')"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to bake version.
    if exist "_version_baked.py" del /q "_version_baked.py"
    pause
    exit /b 1
)

REM Run PyInstaller (no --clean flag for faster rebuilds)
REM --onefile: bundle everything into a single executable
REM --windowed: no console window (GUI app with PySide6)
REM --name: output executable name
REM PyInstaller automatically analyzes imports, so all .py modules are bundled
REM Temp files are cleaned up after successful build in step 4
set EXE_NAME=OscGoesPurrr_!BUILD_VERSION!

REM intiface-engine: bundle the built-in Intiface server binary so "integrated"
REM mode works in the frozen build. The engine is a native per-platform
REM executable that is NOT checked into the repo, so only add the data flag
REM when the binary is actually present — otherwise PyInstaller aborts on a
REM missing --add-data source. Drop intiface-engine.exe into intiface-engine\
REM (see intiface-engine\PLACE_INTIFACE_ENGINE_HERE.txt) to ship integrated mode.
set ENGINE_DATA=
if exist "intiface-engine\intiface-engine.exe" set ENGINE_DATA=--add-data "intiface-engine;intiface-engine"
if defined ENGINE_DATA (echo Bundling built-in intiface-engine.) else (echo intiface-engine binary NOT found in intiface-engine\ - building WITHOUT integrated mode. Drop intiface-engine.exe there to enable it.)

REM steamvr_toy_driver: bundle the prebuilt DLL + manifest + resources so the
REM installer can lay them into %LOCALAPPDATA% at runtime. Only the runtime
REM payload (manifest, bin/win64/*.dll, resources/) needs to ship; src/, include/,
REM build/, and *.bat are stripped via PyInstaller's --add-data globs below.
REM
REM --collect-all openvr: the openvr Python package ships libopenvr_api_64.dll
REM as a plain data file inside its own folder, NOT declared via setup.py. Without
REM --collect-all PyInstaller bundles the .py code but skips the native DLL, so
REM `import openvr` blows up at runtime with no obvious error.
pyinstaller --noconfirm ^
    --onefile ^
    --windowed ^
    --icon "Images\OGP_Icon.ico" ^
    --add-data "Images;Images" ^
    --add-data "steamvr_toy_driver\driver.vrdrivermanifest;steamvr_toy_driver" ^
    --add-data "steamvr_toy_driver\bin;steamvr_toy_driver\bin" ^
    --add-data "steamvr_toy_driver\resources;steamvr_toy_driver\resources" ^
    --add-data "steamvr_toy_driver\icon_assets_64;steamvr_toy_driver\icon_assets_64" ^
    %ENGINE_DATA% ^
    --collect-all openvr ^
    --name "!EXE_NAME!" ^
    main.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] PyInstaller build failed!
    echo Temporary files have been preserved for debugging.
    if exist "_version_baked.py" del /q "_version_baked.py"
    pause
    exit /b 1
)

echo.
echo [4/4] Cleaning up temporary files...

REM Delete the baked version file so source-tree runs go back to live git lookups
if exist "_version_baked.py" (
    echo Deleting _version_baked.py...
    del /q "_version_baked.py"
)

REM Delete .spec files (PyInstaller build blueprints)
for %%f in (*.spec) do (
    if exist "%%f" (
        echo Deleting %%f...
        del /q "%%f"
    )
)

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
echo Executable location: dist\!EXE_NAME!.exe
echo.

REM Check if the exe was created
if exist "dist\!EXE_NAME!.exe" (
    echo [SUCCESS] !EXE_NAME!.exe created successfully!
) else (
    echo [WARNING] Executable not found in dist folder.
)

echo.
pause