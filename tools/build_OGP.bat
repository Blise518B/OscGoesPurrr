@echo off
setlocal enabledelayedexpansion

REM Run from the repo root (this script lives in tools\) so every relative
REM path below (venv\, src\, the --add-data sources, dist\) resolves
REM no matter where the .bat is launched from — e.g. a stale shortcut whose
REM "Start in" still points at the folder's old location after a move.
cd /d "%~dp0.."

echo ========================================
echo   OscGoesPurrr - PyInstaller Build Script
echo ========================================
echo.

REM ------------------------------------------------------------------
REM Resolve a Python launcher (prefer the 'py' launcher over the
REM Microsoft Store 'python' stub) and build / validate a venv. Every
REM python / pip / PyInstaller call below runs through the venv so the
REM build never touches system Python.
REM ------------------------------------------------------------------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo [ERROR] Python not found. Install Python 3.10+ from https://www.python.org/
    pause
    exit /b 1
)

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
        echo [ERROR] Could not create virtual environment.
        pause
        exit /b 1
    )
)

REM A leftover _version_baked.py from an interrupted earlier build would
REM override the live git version below (and a truncated/empty one would
REM poison the exe name). Remove it so the version always resolves fresh.
if exist "src\_version_baked.py" del /q "src\_version_baked.py"

REM Get version from version.py by querying git commit count.
REM NOTE: %VENV_PY% is intentionally UNQUOTED here. Inside `for /f usebackq`,
REM a double-quoted program path combined with quoted args mis-parses on
REM cmd.exe (you get: '...python.exe" -c "from' is not recognized) and the
REM version comes back empty. The path is relative with no spaces, so an
REM unquoted exe is safe here — do NOT re-add the quotes around %VENV_PY%.
echo Resolving version from Git...
for /f "usebackq tokens=*" %%i in (`%VENV_PY% -c "import sys; sys.path.insert(0, 'src'); from version import __version__; print(__version__)"`) do set "BUILD_VERSION=%%i"

REM Fail loudly instead of shipping a mis-named exe (e.g. "OscGoesPurrr_.exe")
REM when the query came back empty — usually a broken venv or git missing.
if not defined BUILD_VERSION (
    echo [ERROR] Version resolution returned empty - aborting so the build
    echo         does not produce a mis-named "OscGoesPurrr_.exe".
    echo         Check that git is on PATH and this is a git checkout, and
    echo         that the venv is healthy ^(delete the venv folder + re-run^).
    pause
    exit /b 1
)
echo Building version: !BUILD_VERSION!
echo.

echo [1/4] Checking for PyInstaller...
"%VENV_PY%" -m pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo PyInstaller not found. Installing...
    "%VENV_PY%" -m pip install pyinstaller -c constraints.txt
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
"%VENV_PY%" -m pip install -r requirements.txt -c constraints.txt
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
echo Baking version into src\_version_baked.py...
"%VENV_PY%" -c "import sys; sys.path.insert(0, 'src'); from version import __version__ as v, _SHORT_HASH as h, build_number; open('src/_version_baked.py','w',encoding='utf-8').write('VERSION = ' + repr(v) + '\nSHORT_HASH = ' + repr(h) + '\nBUILD = ' + repr(build_number()) + '\n')"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to bake version.
    if exist "src\_version_baked.py" del /q "src\_version_baked.py"
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
REM Note: PyInstaller below is invoked via the venv (%VENV_PY% -m PyInstaller).

REM intiface-engine: bundle the built-in Intiface server binary so "integrated"
REM mode works in the frozen build. The engine is a native per-platform
REM executable that is NOT checked into the repo, so only add the data flag
REM when the binary is actually present — otherwise PyInstaller aborts on a
REM missing --add-data source. Drop intiface-engine.exe into src\intiface-engine\
REM (see src\intiface-engine\PLACE_INTIFACE_ENGINE_HERE.txt) to ship integrated mode.
set ENGINE_DATA=
if exist "src\intiface-engine\intiface-engine.exe" set ENGINE_DATA=--add-data "src\intiface-engine;intiface-engine"
if defined ENGINE_DATA (echo Bundling built-in intiface-engine.) else (echo intiface-engine binary NOT found in src\intiface-engine\ - building WITHOUT integrated mode. Drop intiface-engine.exe there to enable it.)

REM Everything the app imports beyond the bundled engine is pure Python, so
REM PyInstaller's own import analysis covers it -- no --collect-all flags
REM needed. (The full edition needs them for openvr's and bleak's native
REM payloads; this edition ships neither.)
"%VENV_PY%" -m PyInstaller --noconfirm ^
    --onefile ^
    --windowed ^
    --icon "src\Images\OGP_Icon.ico" ^
    --add-data "src\Images;Images" ^
    --add-data "LICENSE;." ^
    --add-data "THIRD_PARTY_NOTICES.md;." ^
    %ENGINE_DATA% ^
    --name "!EXE_NAME!" ^
    src\main.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] PyInstaller build failed!
    echo Temporary files have been preserved for debugging.
    if exist "src\_version_baked.py" del /q "src\_version_baked.py"
    pause
    exit /b 1
)

echo.
echo [4/4] Cleaning up temporary files...

REM Delete the baked version file so source-tree runs go back to live git lookups
if exist "src\_version_baked.py" (
    echo Deleting src\_version_baked.py...
    del /q "src\_version_baked.py"
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