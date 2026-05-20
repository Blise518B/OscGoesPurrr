@echo off
REM One-shot helper to grab the OpenVR driver header before the first build.
REM Run from this directory.
setlocal
pushd "%~dp0"
if exist include\openvr_driver.h (
    echo include\openvr_driver.h already present.
    popd
    exit /b 0
)
where curl >nul 2>nul
if errorlevel 1 (
    echo curl not found on PATH. Download
    echo   https://raw.githubusercontent.com/ValveSoftware/openvr/master/headers/openvr_driver.h
    echo and save it as include\openvr_driver.h
    popd
    exit /b 1
)
curl -L -o include\openvr_driver.h https://raw.githubusercontent.com/ValveSoftware/openvr/master/headers/openvr_driver.h
popd
