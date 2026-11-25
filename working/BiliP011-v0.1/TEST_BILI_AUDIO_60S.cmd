@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 新版播放器不再额外衰减到20%%；本次不会改系统音量。
echo 请先把学习笔系统音量降至中低档，并唤醒屏幕，再按任意键试听。
echo 播放约60秒，触屏可提前退出；不切换原厂UI，不启用保亮桥接。
pause
python host\run_media_probe.py --bundle out\media-c7740a1889b5294d --play --volume 100
set "trial_exit=%errorlevel%"
echo 测试退出码：%trial_exit%。实际响度仍请按听感确认。
pause
exit /b %trial_exit%
