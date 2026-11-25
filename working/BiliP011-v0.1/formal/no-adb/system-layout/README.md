# P011 Bili system 布局候选（仅 HOST，未生成镜像）

2026-10-14。新候选 `7d8e33be09953969b7670025`，状态
`HOST_LAYOUT_CANDIDATE_NOT_IMAGE_NOT_FLASHED`。这是本地私有的文件布局与首次启动候选；不是可刷镜像、免 ADB 用户安装器或设备验收结果。只在本目录写文件，没有调用 ADB/USB/串口、执行 ARM 程序、挂载 ext4、运行 fsck 或改原 `p29-system.img`，没有重复旧版测试。

## 已确认的原厂启动链

对现有 v2.4.0 原镜像作两次互补的定点 `debugfs -R` 只读导出，不使用 `-w`。Docker 原镜像只读、项目 `/src` 只读，只有本目录 `/out` 可写，容器无网络；没有重新扫描或计算整个 1 GiB 镜像 hash。

- `/sbin/init` 是 `/sbin/init.sysvinit` 的符号链接；后者已导出，仅静态确认 ARM32 ELF，没有执行。
- `/etc/inittab` 指定默认 runlevel 5，sysinit 调 `/etc/init.d/rcS`，runlevel 5 调 `/etc/init.d/rc 5`。
- rcS 正常分支 `exec /etc/init.d/rc S`；rc 按 `/etc/rc$runlevel.d/S*` 顺序调用 `start`。
- `/etc/rcS.d/S04mountall.sh -> ../init.d/mountall.sh`；mountall 按 fstab 挂载。fstab 将 p40 挂到 `/mnt/userdata`，再将本设备 `/mnt/userdata/data` 绑定到 `/mnt/data`。
- rc5 中已有 S09weston、S90control_engine-init、S96zybz03qt-init。新布局只新增独立的 S99p011-bili-system；不改 init、rcS、rc、fstab、原厂 launcher 或 control_engine。

原始命令 stdout/stderr/exit、定点导出文件与 hash 位于 `evidence/startup-targeted`、`evidence/startup-followup`。`startup-export.*`、`startup-followup.*` 分别保存 Docker 外层双流/退出。源镜像基线 SHA 沿用已经独立重算通过的 `6bf4706e5f03ed79edfe0e4ab337dbcc1310d6a7b57116a09ecfa756b4de648f`，不把复用历史 hash 写成本次全镜像重检。

## 新布局

`out/7d8e33be09953969b7670025/system-files` 是普通文件覆盖层，不是磁盘镜像。原正式包的69个 manifest 输入先逐项读回匹配，再派生独立身份。新 overlay 有70个普通文件，合计35,261,936字节，另有3项**仅记录在 manifest 的符号链接**，尚未应用到任何文件系统镜像。

| 内容 | 设备候选位置 |
| --- | --- |
| 不可变 QML/Python、播放器与私有库 | `/opt/p011-bili/releases/7d8e33be09953969b7670025/app`、`media` |
| 精确页面入口替换 | `/usr/bin/Z03` 中原 `SetUserReport.qml` 唯一资源记录，指向上述 `FeedbackEntry.qml` |
| 独立启动脚本 | `/etc/init.d/p011-bili-system` |
| 启动链接 | `/etc/rc5.d/S99p011-bili-system -> ../init.d/p011-bili-system` |
| 正常退出链接 | `/etc/rc0.d/K05p011-bili-system`、`/etc/rc6.d/K05p011-bili-system`，同一目标 |
| 每台设备自己的运行目录 | `/mnt/data/p011-toolbox/bili-awake/7d8e33be09953969b7670025` |
| 每台设备自己的账号、历史、偏好 | 原自有 `bili-account`、`bili-library`、`bili-preferences` 路径；已有字节保留 |

Z03 新 SHA 为 `40ed2986a58c13ee59160f34e874b3dc8eb1d74d4156083878dfee1ea9d4bdbe`。构建时实际解出并比较400个资源，只有 `SetUserReport.qml` 改变，其余399个、SetMainPage及该资源记录之外的全部二进制字节保持；“用户反馈”设置名称、图标、source 和排序不改。

`system_bootstrap.py.in` 在生成时注入新身份。实际执行仍只允许 P011 ARMv7/root、固定 release 位置、精确 v2.4.0、普通启动模式及唯一可写 p40 `/mnt/data` 挂载。它只创建本项目自己的0700目录，拒绝符号链接、非目录、其他 owner、非私有权限与非法身份，保留已有账号/历史/偏好内容；没有导入开发机 userdata、NV、cookie 或任何个人文件。

启动/停止由同一自有 flock 串行，启动固定 Python 服务，使用私有 HOME/TMP/XDG 路径和只读 app/media。停止只对精确 argv/exe/UID、同 PID/starttime 的本服务发送 SIGTERM，有界等待，不强杀、不按进程名批量结束其他程序。服务的常驻模式与页面退出清理沿用已冻结旧业务逻辑；不宣称退出后后台占用归零。

## 首次 HOST 证据与限制

新布局 builder 首次运行 exit=0；12项新 HOST 检查首次运行全部通过，见 `build.stdout.raw`、`build.stderr.raw`、`build.exit.txt` 与 `host-tests.stdout.raw`、`host-tests.stderr.raw`、`host-tests.status.json`。检查覆盖所有 overlay 成员读回与 media hash闭合、路径、新身份、启动脚本 `sh -n`、Python3.5语法、无字体、正常/特殊启动门禁、p40挂载门禁、首次目录创建、既有用户字节保留、符号链接/权限拒绝，以及 PID复用/进程身份变化时不发信号。仅执行 HOST代码和模拟检查，没有在 HOST启动播放器/服务或执行候选 start/stop。

manifest 记录 root文件目标权限及 uid/gid，Windows上的普通目录不承担最终 Unix权限/符号链接语义。后续镜像构建器必须严格应用并验证这些元数据。当前没有生成候选 image，更没有刷入、目标回读或启动新镜像。

下一步仍需当前目标的免ADB system身份与原件回读、可信写入/恢复路线、独立镜像构建与完整验证，以及真实启动/data挂载/入口/退出/重启/原厂业务验收；之后才能做跨电脑便携用户包。原 system 镜像、旧正式包及历史失败证据均保持。
