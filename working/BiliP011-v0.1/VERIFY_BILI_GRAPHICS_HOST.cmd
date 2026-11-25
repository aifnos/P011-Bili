@echo off
setlocal
cd /d "%~dp0"
echo P011 graphics investigation: PC-only tests and saved trace analysis.
echo No ADB, Docker startup, device window, reboot or firmware operation.
python host\verify_graphics_host.py
set "P011_GRAPHICS_TEST_EXIT=%ERRORLEVEL%"
echo.
echo This is HOST evidence, not a new device playback or physical acceptance.
pause
exit /b %P011_GRAPHICS_TEST_EXIT%
