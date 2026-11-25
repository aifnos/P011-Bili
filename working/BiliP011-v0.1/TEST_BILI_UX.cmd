@echo off
setlocal
cd /d "%~dp0"
echo P011 UX candidate: temporary 10-minute session. No automatic playback.
echo The default media selection and factory firmware are not replaced.
python host/ux_trial.py
if errorlevel 1 echo Test failed. Keep the printed log directory; do not restart an old candidate.
pause
