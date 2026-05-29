@echo off
REM Convenience launcher: build only the C++ SteamVR toy driver DLL.
REM Use this when you've edited steamvr_toy_driver\src\driver.cpp and want
REM to rebuild the DLL WITHOUT also rebuilding the full Python EXE.
REM
REM After this finishes, either:
REM   * click "Reinstall toy driver" inside OscGoesPurrr's Settings tab to
REM     copy the new DLL into %LOCALAPPDATA% and restart SteamVR, OR
REM   * run build_OGP.bat (the outer one) to repackage the EXE with the new DLL.
REM
REM Don't confuse this with build_OGP.bat - that one builds the whole Python EXE.

call "%~dp0steamvr_toy_driver\build_driver.bat"
