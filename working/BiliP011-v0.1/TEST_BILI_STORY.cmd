@echo off
setlocal
cd /d "%~dp0"
echo P011 Bili: two-item opening-segment cache, comments and speed controls.
echo Fresh session, maximum 10 minutes. No autoplay or permanent installation.
python -X utf8 host/story_trial.py --media media-6d99b414a032ec70
if errorlevel 1 goto failed
echo Recovery passed. Keep the printed SAFE_RESULT_ZIP path.
pause
exit /b 0
:failed
echo Test FAILED. Preserve logs and verify restoration before another trial.
pause
exit /b 1
