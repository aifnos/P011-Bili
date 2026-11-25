@echo off
setlocal
cd /d "%~dp0"
echo P011 Bili fixed-source screen alignment, two fresh muted sessions.
echo Each session restores stock. No login, quality switch or firmware writes.
python -X utf8 host/performance_trial.py --media out/media-aa0c285af8c604c5 --quality 32 --ux-state --window-pose landscape
if errorlevel 1 goto failed
python -X utf8 host/performance_trial.py --media out/media-aa0c285af8c604c5 --quality 32 --ux-state --window-pose portrait
if errorlevel 1 goto failed
python -X utf8 host/stock_restore_audit.py
if errorlevel 1 goto failed
echo Machine checks passed. Physical sound and finger-touch remain manual.
echo Share only SAFE_RESULT_ZIP, not account files or raw factory logs.
pause
exit /b 0
:failed
echo Test FAILED. Keep the printed logs. Do not rerun an archived session.
pause
exit /b 1
