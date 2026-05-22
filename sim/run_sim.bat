@echo off
REM Launches the VRChat simulator from the project root.
REM Stays entirely separate from the main app — never imports it.

pushd "%~dp0\.."
python -m sim
popd
