@echo off
setlocal
cd /d "%~dp0"
echo P011 UX: finite muted device tests. No flashing, factory reset or automatic reboot.
echo Each run creates a fresh guarded session and restores the stock UI.
echo Test 1: full UI, playback, Story replay, cache and 130-second awake hold.
python host/ux_trial.py --automated --soak-seconds 130 --soak-bvid BV1R7eg6gEnJ
if errorlevel 1 goto failed
echo Test 2: unavailable-stream recovery, resume, restart and isolated history clear.
python host/ux_trial.py --automated --state-probe
if errorlevel 1 goto failed
python host/stock_restore_audit.py
if errorlevel 1 goto failed
echo Automated checks passed. Sound and physical touch still need a person.
echo Keep the printed SAFE_RESULT_ZIP paths. Do not share factory raw logs.
pause
exit /b 0
:failed
echo Test FAILED. Keep the printed logs; do not automatically rerun archived sessions.
echo Review the recovery result before starting another device test.
pause
exit /b 1
