@echo off
setlocal
cd /d "%~dp0"
echo P011 bounded synthetic AVC 60fps decoder tests: 480x270, 640x360, 1280x720.
echo Requires host ffmpeg/ffprobe and an idle root-ADB P011 on the pinned firmware.
echo No display, audio, Bili stream, clock change, system write or default change.
echo Each test generates its own input, verifies identity and removes only its own device files.
echo Results and a numeric safe ZIP are saved under the project logs directory.
pause
python host\screen_rate_trial.py --width 480
if errorlevel 1 goto failed
python host\screen_rate_trial.py --width 640
if errorlevel 1 goto failed
python host\screen_rate_trial.py --width 1280
if errorlevel 1 goto failed
echo All decoder tests passed. This is NOT full-player or physical panel 60fps acceptance.
goto done
:failed
echo A test did not pass. Preserve its logs and verify stock state before retrying.
pause
exit /b 1
:done
pause
exit /b 0
