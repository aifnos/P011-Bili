@echo off
setlocal
cd /d "%~dp0"
echo Finite muted Story preload and direct-controls acceptance.
echo No account actions, pairing, firmware writes or automatic reboot.
python -X utf8 host/story_trial.py --media media-6d99b414a032ec70 --automated
if errorlevel 1 goto failed
python host/stock_restore_audit.py
if errorlevel 1 goto failed
echo Scoped machine checks passed; not zero-latency or full-regression proof.
echo Real touch and listening remain manual. Share only SAFE_RESULT_ZIP.
pause
exit /b 0
:failed
echo Test FAILED. Preserve logs; do not rerun an archived session.
pause
exit /b 1
