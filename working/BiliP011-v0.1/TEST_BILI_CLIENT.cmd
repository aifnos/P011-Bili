@echo off
setlocal
cd /d "%~dp0"
echo P011 Toolbox + Bili enhanced - temporary 10 minute test, NOT permanent installation.
echo Wake the pen and lower system volume to medium before continuing.
echo No video autoplays. Open Bili from Toolbox. Bili's Toolbox button returns home.
echo Exit from Toolbox restores the factory interface; 10 minute timeout is automatic.
echo Login is optional; cookies remain private on the pen, outside result ZIPs.
pause
python host\client_oneclick.py
echo.
echo Read the recovery result above. A running factory process is not physical acceptance.
pause
