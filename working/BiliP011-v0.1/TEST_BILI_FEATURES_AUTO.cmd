@echo off
setlocal
cd /d "%~dp0"
echo Finite muted public-feature tests. Account writes and login are disabled.
echo Each phase creates a fresh guarded candidate and restores stock.
python host/feature_trial.py --automated
if errorlevel 1 goto failed
python host/feature_trial.py --automated --regression
if errorlevel 1 goto failed
python host/stock_restore_audit.py
if errorlevel 1 goto failed
echo Machine checks passed. Sound, real touch and account actions need a person.
echo Share SAFE_RESULT_ZIP only, not raw factory logs or account files.
pause
exit /b 0
:failed
echo Test FAILED. Preserve the printed logs; do not rerun an archived session.
pause
exit /b 1
