@echo off
setlocal
cd /d "%~dp0"
echo P011 bounded, muted presentation-feedback diagnostic (not the default player).
echo Runs a fixed public 1080P60 sample, captures only after pause, then restores stock.
echo Requires root ADB, network and the pinned v2.4.0 firmware. No clock/system changes.
echo Results separate submitted frames, compositor-presented video and refresh timing.
echo Press Ctrl+C here to cancel before starting, or any key to continue.
pause
python host\performance_trial.py --media out\media-dd9ae6238e4fe4fe --quality 116 --bvid BV1gi4y1V7Xx --require-presentation --require-fused-copy --require-output-cache cached --require-cached-retention --require-rate-states
if errorlevel 1 goto failed
echo Finite diagnostic and restoration passed. This does NOT imply full source-rate playback.
pause
exit /b 0
:failed
echo Diagnostic incomplete or failed. Preserve logs and check restoration before retrying.
pause
exit /b 1
