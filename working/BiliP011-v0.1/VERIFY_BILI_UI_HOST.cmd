@echo off
setlocal
cd /d "%~dp0"
set "QT_QPA_PLATFORM=offscreen"
set "QT_QUICK_BACKEND=software"
echo PC-only Qt fixtures. No ADB, Docker, device launch or live Bili login.
python -m unittest discover -s host -p "test_*.py"
if errorlevel 1 goto failed
python host/preview_client.py --embedded
if errorlevel 1 goto failed
python host/test_qml_automation.py --toolbox --archive
if errorlevel 1 goto failed
echo HOST UI checks complete. Gallery and host-only ZIP paths are printed above.
pause
exit /b 0
:failed
echo HOST UI checks FAILED. Keep the printed log directory for diagnosis.
pause
exit /b 1
