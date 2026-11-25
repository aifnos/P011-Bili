# BiliP011 正式写入程序

> 2026-10-14分发要求已澄清：用户要求完全不依赖ADB、在不同电脑给普通用户刷入。下面现有包仍是root ADB开发候选，不能作为符合该要求的分发版。免ADB通道尚未完成写入/回读/恢复实测，详见[免ADB分发状态](NO_ADB_DISTRIBUTION.md)。历史包保持原样。

本轮用户明确要求制作正式写入程序，入口为“设置 → 用户反馈”，保持原名。新程序独立于历史十分钟试验入口，不修改旧包或历史结果。

- 项目根入口：`D:\project\P011\一键正式写入B站.cmd`。
- 原反馈页恢复：`D:\project\P011\一键恢复用户反馈.cmd`。
- 最终完整私有包：`out/P011-Bili-Formal-v1-final-20261014.private.zip`。
- 最终运行release：`9412e49de8feb2d6b2677180`；仅支持钉扎的v2.4.0固件与原厂三文件。
- 详细报告：`D:\project\P011\04_Documents\P011-Bili正式写入包与用户反馈入口-20261014.md`。

当前状态是 **HOST_BUILT_DEVICE_PENDING**。正式包已构建并校验，制作时ADB无设备，尚未向P011写入或进行实机设置入口/重启/声音验收。`out/P011-Bili-Formal-v1-20261014` 是较早的电脑装配快照，保留原样，不作为入口。

复现构建使用 `host/build_native.py`、`host/build_formal.py` 和 `host/package_formal.py`，输出目录必须是新目录。不要运行历史START，不把旧goal中的“临时候选”自动用于本次正式写入，也不要把本次用户授权扩大到无线、NV、系统库、USB、其他设置项或完整固件写入。
