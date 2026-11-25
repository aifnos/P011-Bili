@echo off
setlocal
cd /d "%~dp0"
echo P011 performance diagnostics: PC-only regression checks.
echo No ADB, Docker, playback, reboot, or firmware operation.
python host\verify_performance_host.py
set "P011_PERFORMANCE_TEST_EXIT=%ERRORLEVEL%"
echo.
echo Host checks are not device performance or physical acceptance.
pause
exit /b %P011_PERFORMANCE_TEST_EXIT%
