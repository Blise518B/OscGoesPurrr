@echo off
REM Build the OscGoesPurrr SteamVR toy driver (driver_oscgoespurrr.dll).
REM Safe to double-click from Explorer. ALWAYS pauses at the end so you can
REM read the output regardless of success / failure.

setlocal
pushd "%~dp0"

echo === Building OscGoesPurrr SteamVR toy driver ===
echo Working dir: %CD%
echo.

where cl.exe >nul 2>nul
if not errorlevel 1 goto have_vs_env

echo cl.exe not on PATH. Searching for Visual Studio Build Tools...

set "VSWHERE_A=C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
set "VSWHERE_B=C:\Program Files\Microsoft Visual Studio\Installer\vswhere.exe"
set "VSWHERE="
if exist "%VSWHERE_A%" set "VSWHERE=%VSWHERE_A%"
if not defined VSWHERE if exist "%VSWHERE_B%" set "VSWHERE=%VSWHERE_B%"
if defined VSWHERE goto have_vswhere

echo.
echo === ERROR: vswhere.exe not found.
echo Install Visual Studio Build Tools 2019 or 2022 with the
echo "Desktop development with C plus plus" workload from:
echo     https://aka.ms/vs/17/release/vs_BuildTools.exe
goto err

:have_vswhere
set "VSPATH="
for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSPATH=%%i"
if defined VSPATH goto have_vspath

echo.
echo === ERROR: no MSVC C plus plus toolchain found via vswhere.
echo Add the "Desktop development with C plus plus" workload, then re-run.
goto err

:have_vspath
set "VCVARS=%VSPATH%\VC\Auxiliary\Build\vcvars64.bat"
if exist "%VCVARS%" goto have_vcvars

echo === ERROR: vcvars64.bat missing at:
echo     %VCVARS%
goto err

:have_vcvars
echo Found Visual Studio at: %VSPATH%
echo Loading VS x64 env...
call "%VCVARS%"
if errorlevel 1 goto err
echo.

:have_vs_env

if not exist build mkdir build
echo === Running CMake configure ===
cmake -B build -A x64 -DCMAKE_BUILD_TYPE=Release
if errorlevel 1 goto err
echo.

echo === Running CMake build ===
cmake --build build --config Release
if errorlevel 1 goto err
echo.

echo === Build succeeded.
echo Output: %~dp0bin\win64\driver_oscgoespurrr.dll
echo.
echo You can now close this window. Next: re-run the outer build_OGP.bat to
echo bundle the fresh DLL into a new OscGoesPurrr EXE.
echo.
pause
popd
exit /b 0

:err
echo.
echo === Build FAILED. See messages above for details.
echo.
pause
popd
exit /b 1
