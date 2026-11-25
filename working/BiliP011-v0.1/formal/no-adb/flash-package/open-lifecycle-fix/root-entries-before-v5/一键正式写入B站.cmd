@echo off
chcp 65001 >nul
call "%~dp0working\BiliP011-v0.1\formal\no-adb\flash-package\out\P011-Bili-NoADB-v4-ready-20261014\一键正式写入B站.cmd"
exit /b %ERRORLEVEL%
