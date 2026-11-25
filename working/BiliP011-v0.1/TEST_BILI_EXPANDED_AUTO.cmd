@echo off
setlocal
cd /d "%~dp0"
echo Three finite muted trials, each with its own automatic stock restoration.
echo Account writes and login are disabled. No LAN service or firmware write.
python -X utf8 host/catalog_trial.py --media media-aa0c285af8c604c5 --automated
if errorlevel 1 goto failed
python -X utf8 host/feature_trial.py --media media-aa0c285af8c604c5 --automated
if errorlevel 1 goto failed
python -X utf8 host/window_placement_trial.py --media media-aa0c285af8c604c5 --automated
if errorlevel 1 goto failed
python host/stock_restore_audit.py
if errorlevel 1 goto failed
echo Machine checks passed. Physical experience and account writes remain manual.
echo Share only SAFE_RESULT_ZIP, not account files or raw factory logs.
pause
exit /b 0
:failed
echo Test FAILED. Keep the printed logs. Do not rerun an archived session.
pause
exit /b 1
