@echo off
chcp 65001 >nul
call "%~dp0working\BiliP011-v0.1\formal\no-adb\flash-package\out\P011-Bili-NoADB-v4-ready-20261014\一键恢复原系统.cmd"
exit /b %ERRORLEVEL%
