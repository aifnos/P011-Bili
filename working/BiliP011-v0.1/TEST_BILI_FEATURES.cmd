@echo off
setlocal
cd /d "%~dp0"
echo P011 official-feature candidate: fresh temporary session, 10-minute maximum.
echo No automatic playback, login, likes, coins or favorites. No firmware write.
python host/feature_trial.py
if errorlevel 1 goto failed
echo Stock recovery checks passed. Keep the printed SAFE_RESULT_ZIP path.
pause
exit /b 0
:failed
echo Test FAILED. Preserve logs and verify restoration before a new test.
pause
exit /b 1
