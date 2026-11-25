@echo off
setlocal
cd /d "%~dp0"
echo P011 Toolbox + Bili continuous playback / backlight check.
echo This runs public UI checks and a 130-second MUTED playback hold.
echo Leave the pen untouched. System volume and the 60-second idle setting are not changed.
echo Max 10 minutes, then guarded restoration. This is NOT permanent installation.
pause
python host\client_oneclick.py --automated --soak-seconds 130
echo.
echo Read recovery and soak results. Only share the safe ZIP, not raw factory logs.
pause
