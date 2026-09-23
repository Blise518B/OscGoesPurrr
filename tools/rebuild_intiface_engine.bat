@echo off
REM ===========================================================================
REM  Rebuild the bundled Intiface engine (Buttplug spec-v4) and drop it into
REM  OscGoesPurrr\src\intiface-engine\.
REM
REM  Run this whenever the engine needs updating (e.g. the Buttplug protocol
REM  moves and integrated mode stops connecting). It reuses the kept monorepo
REM  clone + its cargo build cache in _engine_build\, so the rebuild is a fast
REM  INCREMENTAL build, not the ~15-min cold compile.
REM
REM  Lives in the repo root, next to the gitignored _engine_build\ clone.
REM
REM  The build strips this machine's paths out of the binary. Rust and C both
REM  bake source file paths into the exe (panic locations, __FILE__ in asserts),
REM  and here those paths run through %USERPROFILE% -- so a plain build ships
REM  the Windows account name inside every public release. RUSTFLAGS remaps
REM  the Rust side; CFLAGS /d1trimfile trims the C side (aws-lc-sys), in both
REM  the long and the 8.3 short spelling, because its build script converts
REM  paths to short names. A subst drive does NOT work: the short-name
REM  conversion resolves it straight back to the real path.
REM  Verify after a rebuild: the exe must not contain the account name.
REM
REM  Close OscGoesPurrr before running, or the copy step fails on a locked .exe.
REM ===========================================================================
setlocal EnableDelayedExpansion

for %%I in ("%~dp0..") do set "ROOT=%%~fI\"
set "ENGINE_REPO=%ROOT%_engine_build\buttplug"
set "DEST_DIR=%ROOT%src\intiface-engine"
set "DEST=%DEST_DIR%\intiface-engine.exe"
set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"

if not defined CARGO_HOME set "CARGO_HOME=%USERPROFILE%\.cargo"
set "REGDIR="
for /d %%d in ("%CARGO_HOME%\registry\src\index.crates.io-*") do if not defined REGDIR set "REGDIR=%%~fd"
set "RUSTFLAGS=--remap-path-prefix=%CARGO_HOME%=/cargo --remap-path-prefix=%USERPROFILE%\.rustup=/rustup --remap-path-prefix=%ENGINE_REPO%=/buttplug"
set "CFLAGS="
if defined REGDIR (
    for %%s in ("!REGDIR!") do set "REGDIR_SHORT=%%~fss"
    set "CFLAGS=/d1trimfile:!REGDIR!\ /d1trimfile:!REGDIR_SHORT!\"
)

if not exist "%ENGINE_REPO%\Cargo.toml" (
    echo ERROR: engine clone not found at:
    echo     %ENGINE_REPO%
    echo.
    echo Re-clone it with:
    echo     git clone https://github.com/buttplugio/buttplug "%ENGINE_REPO%"
    goto :fail
)

echo === [1/4] Updating monorepo ^(git pull --ff-only^) ===
pushd "%ENGINE_REPO%"
git pull --ff-only
if errorlevel 1 echo   (no fast-forward / pull skipped - building current checkout)

echo.
echo === [2/4] Building intiface-engine (release, incremental) ===
cargo build --release --bin intiface-engine
if errorlevel 1 (
    echo ERROR: cargo build failed. See output above.
    popd
    goto :fail
)
popd

echo.
echo === [3/4] Copying engine into OscGoesPurrr ===
if not exist "%DEST_DIR%" mkdir "%DEST_DIR%"
copy /Y "%ENGINE_REPO%\target\release\intiface-engine.exe" "%DEST%" >nul
if errorlevel 1 (
    echo ERROR: copy failed. Is OscGoesPurrr still running? Close it and retry.
    goto :fail
)

echo.
echo === [4/4] Done. Placed engine version: ===
"%DEST%" --version

echo.
echo Engine rebuilt and placed at:
echo     %DEST%
echo Run it live with "python src\main.py", or run tools\build_OGP.bat to bake it into a
echo frozen .exe.
echo.
pause
endlocal
exit /b 0

:fail
echo.
echo Rebuild did NOT complete.
echo.
pause
endlocal
exit /b 1
