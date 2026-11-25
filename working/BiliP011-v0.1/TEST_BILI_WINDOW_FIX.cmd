@echo off
setlocal
cd /d "%~dp0"
echo P011 Bili window alignment candidate. Fresh session, maximum 10 minutes.
echo No automatic playback or account actions. No permanent installation.
python -X utf8 host/window_placement_trial.py --media media-aa0c285af8c604c5
if errorlevel 1 goto failed
echo Recovery passed. Keep the printed SAFE_RESULT_ZIP path.
pause
exit /b 0
:failed
echo Test FAILED. Preserve logs and verify restoration before another trial.
pause
exit /b 1
