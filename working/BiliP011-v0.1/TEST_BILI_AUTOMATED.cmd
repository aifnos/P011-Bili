@echo off
setlocal
cd /d "%~dp0"
echo P011 Toolbox + Bili automatic regression, max 10 minutes.
echo This will click public candidate pages, save screenshots and play MUTED video.
echo It does not capture account/QR pages, change system volume or install permanently.
echo Leave the connected pen alone until recovery is confirmed below.
pause
python host\client_oneclick.py --automated
echo.
echo Only share the safe ZIP. Physical sound and touch acceptance remain separate.
pause
