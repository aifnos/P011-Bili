@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo P011 临时保亮测试：先唤醒学习笔并停在主界面。
echo 即将短暂切换原厂界面副本，播放两分钟，再检查自动息屏并恢复原厂。
echo 不刷机，不替换原厂文件；播放中不要触屏，点屏幕会提前退出。
python host\awake_oneclick.py
set "trial_exit=%errorlevel%"
echo 测试程序退出码：%trial_exit%
pause
exit /b %trial_exit%
