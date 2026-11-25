# 免ADB正式写入的后续实现边界

> v6模式交接修订及冷启动实测（2026-10-14）：用户v5已恢复一次CreateFileW433并发送MODE，但强制观察重枚举超时；未发SYNC或分区命令。v6保留MODE后旧句柄被动读取窗口，处理限定阶段的旧句柄失效，允许同节点沿用，仍以精确协议应答确认AutoD。30项HOST通过；实机冷启动初始化、GPT32KiB和uboot1MiB读取通过、基线SHA一致、277次TX/276帧RX离线复核、MODE及初始SYNC各1、无分区写入、HOST0/句柄关闭，用户确认原厂开机。正式包engine与本轮实测完全相同；system写入/修改镜像启动/B站/恢复和干净电脑仍待。新包 `packages/P011-Bili-NoADB-v6-handoff-20261014.zip`，SHA256 `da00e7f0c48a3abb553b8fa81303984bf12d11305b5d994614da98b7d0d1b1ac`；用户原目录旁已有v6，根入口已切换。详见 `04_Documents/P011-Bili模式交接修订与冷启动读取实测-20261014.md`；以下为历史。

> v5串口打开修订（2026-10-14）：用户v4首次节点已就绪，但打开/初始化报告WinError433；MODE/SYNC/写入均0，原wire TX/RX为0字节，旧日志不足以定位具体API。本版在已确认失败句柄关闭、同设备身份及协议未尝试条件下限时重新识别打开；禁止重发MODE、SYNC和分区命令，新增API/错误码/关闭结果/调用栈证据。48项HOST检查、用户中文路径校验和ZIP全成员核验通过。新包 `packages/P011-Bili-NoADB-v5-open-20261014.zip`，SHA256 `2613d7d46222d78310e2feda99814c6c4b152e15c63c4e149be7c61722cfbbfa`，原用户目录旁已有v5，根入口已切换。真实433恢复、system及干净电脑验收仍待；本轮无设备命令或驱动安装。详见 `04_Documents/P011-Bili串口打开生命周期修订-20261014.md`；以下为历史。

> v4首次就绪修订（2026-10-14）：用户v3停止于首次节点未就绪，open/MODE/SYNC/写入均0，原wire TX/RX为0字节；驱动包已注册，原日志未保存具体未就绪字段。补齐同实例首次启动/COM分配的3秒限时观察，持续异常报告实际状态，保留v3模式后重枚举和存储断连拒绝。8项新HOST＋1项受影响完整模拟连接、用户中文路径校验和ZIP成员校验通过。新包 `packages/P011-Bili-NoADB-v4-ready-20261014.zip`，SHA256 `c6f3cf342f42fb8ed5d27e26827d29b885fef4327a836560002effad7591937c`，原用户目录旁已有v4、根入口已切换。system设备验收仍待，本轮无驱动安装或设备命令。详见 `04_Documents/P011-Bili首次接口就绪等待修订-20261014.md`；以下为历史。

> v3重枚举修订（2026-10-14）：用户v2原始TX只有一次MODE、RX只有回显，无实际SYNC/分区命令，原失败保留。修正MODE后固定0.5秒即重开句柄的时序缺口，改为单次MODE后限时观察同一设备重枚举并稳定；存储断连/多设备/身份变化仍拒绝。8项新HOST和用户中文路径纯校验通过。新包 `packages/P011-Bili-NoADB-v3-reenum-20261014.zip`，SHA256 `4cee68335a5038714865ab8ca42b7853645566a70c4eb627aabb6e16ad4159e4`；原使用目录旁已有v3，根入口也已切换。设备初始化及system实机验收仍待，本轮未操作设备。详见 `04_Documents/P011-Bili下载接口重枚举修订-20261014.md`。以下为历史阶段。

> 含驱动免ADB包已制作（2026-10-14）：`packages/P011-Bili-NoADB-v2-driver-final-20261014.zip`，144,585,149B，SHA256 `682b2a8825f3af8e728e66bb58100d30780a6dba2a0b4888084e8b5e5c8590d4`。内置与此前实测一致的UNISOC VCOM 4.20.42.134，CAT和INF/SYS/DLL签名全过；写入/恢复前自动检查，缺少则经Windows UAC预装，已安装跳过，失败或要求重启时停止。10项新HOST检查、修正OEM INF路径后的本机只读识别、中文空格路径/隔离运行时和ZIP全成员验证通过。system载荷未改，复用v1已过证据。**仍待干净PC驱动首装和system实机写入/启动/功能/恢复，本轮没有驱动安装或设备操作。** 根入口已接v2，增加单独驱动入口；详见 `04_Documents/P011-Bili免ADB含驱动刷写包-20261014.md`。以下无驱动/未生成等为历史阶段。

> 免ADB刷写包已制作（2026-10-14）：`P011-Bili-NoADB-v1-final-20261014.zip` 位于项目 packages，144,923,039B，SHA256 `a8990f40cd38d3b5a7e1d9490268f576cea7001d044b5b61e61995d068666fbf`。新写入/恢复/校验入口、自带隔离Python、按设备备份和完整1GiB system写入/回读程序已打包；设置入口保留“用户反馈”原名。原/候选fsck、13,292原文件项比对、11项新HOST检查、实际全镜像差分重建、中文空格路径与ZIP全部成员读回通过。**状态HOST_PACKAGE_BUILT_VERIFIED_DEVICE_PENDING：本轮未操作设备，成品system刷入/启动/播放/退出/恢复及干净电脑驱动首装未验。** 仅接受固定v2.4底包，电脑需已有厂商签名SPRD下载驱动。根写入和恢复入口现接此免ADB包；完整说明见 `04_Documents/P011-Bili免ADB刷写包制作-20261014.md`。下方“当前/未生成/拦截”等保留为当时历史阶段，不覆盖本条最新状态。

> 最新下载模式实测（2026-10-14）：sysdumpdb 10 MiB 原件双备份、单次完整写回与完整回读通过，WRITE START/MIDST/END 为 1/2560/1 且全部 ACK；GPT、uboot、miscdata、uboot_log 写前后逐字节一致，原始 TX/RX 10790 对离线复核通过。全程无 ADB，writer/parent exit0、句柄关闭，用户确认拔线后正常进入原厂主界面。仅签原件写回应答和回读一致，不证明改变位持久化、system 修改镜像接受、B站安装、完整恢复或跨PC分发。原失败和旧证据保留，详见 04_Documents/P011-下载模式原件写回实测-20261014.md；以下为历史阶段。

2026-10-14。当前真实证据为AutoD握手通过、用户确认拔USB正常开机回原厂主页。当前没有修改镜像写入/回读/启动/恢复验收；本文件是离线核对结果和后续方案，不是已实现的刷入能力。本轮握手会话已经结束，不继续操作设备。

> 后续已落实部分（20:12）：实际init/data挂载链已定点确认，新system布局候选7d8e33be09953969b7670025及其HOST12项已完成；固定storage_read_codec与StageGate、gpt_readback离线校验及便携runtime也有首次HOST证据。完整存储客户端、候选image、当前原件回读、设备写入/恢复与干净电脑验证仍待。下方“需确认/未实现”反映本文件初始阶段，最新实现详见`04_Documents/P011-免ADB一键包实现进度-20261014.md`。

## 现有存储通道证据

历史`05_Logs/original-archives/P011-AutoD-PartitionList-20260914-031854984.zip`内raw tool-stderr显示：CRC16握手后，第一次空EXEC_DATA切入SUM16阶段；SUM16 CONNECT、KEEP_CHARGE、第二次空EXEC_DATA后获得0x0096/256字节能力包，再经工具设置读到user_partition前32768字节/GPT和40分区。没有外部FDL上传，也没有分区写入。

固定原始源码解释两次EXEC：第一次改变AutoD模拟协议阶段，第二次执行设备内置do_download。存储处理器注册读0x10/11/12和写0x01/02/03；这是上游源码能力，尚未匹配当前P011实际构建的写保护与镜像接受条件。[AutoD源码](https://raw.githubusercontent.com/sprd-linux/u-boot15/fb48fd09a42695ff1082a04c636f7ead3fd8850f/common/loader/autodloader_mode.c)、[处理器注册](https://raw.githubusercontent.com/sprd-linux/u-boot15/fb48fd09a42695ff1082a04c636f7ead3fd8850f/common/cmd_download.c)

历史工具的DISABLE_WRITE_RAW_DATA只关闭加速rawdata分支，普通分区写仍存在，不能据此判断设备禁止全部写入。[固定工具版本](https://raw.githubusercontent.com/TomKing062/spreadtrum_flash/2a202404a7512026d146b62624f089aceb408520/spd_dump.c)、[普通写入实现](https://raw.githubusercontent.com/TomKing062/spreadtrum_flash/2a202404a7512026d146b62624f089aceb408520/common.c)

写入START可能先处理写保护与system root标记；**不得用零字节START试探写权限**。内置下载循环还可能记录日志，因此后续应准确描述为“主动切换内置执行阶段，只发送固定存储读命令”，不能承诺设备内部绝无日志落盘。[vendor写入处理器](https://raw.githubusercontent.com/sprd-linux/u-boot15/fb48fd09a42695ff1082a04c636f7ead3fd8850f/common/dloader/dl_cmd_proc.c)

## 下一设备阶段的最小具体范围

另写独立、有界的读取客户端和HOST模拟验证，不自动执行归档脚本，不放开现握手transport的白名单。新阶段尚未实现或执行。

1. 新一轮插入/握手。MODE/握手预算与存储阶段分开，原轮claim已消耗，不能复用。
2. 两次空EXEC各一次，逐阶段核验CRC16→SUM16版本、CONNECT ACK及严格0x96/256能力包；每个错误停止，不回退未知协议。若采用KEEP_CHARGE或DISABLE_TRANSCODE，单列主动动作和预算。旧READ_FLASH_INFO两次无回应，不当作必需步骤盲目复制。
3. 存储读取只允许`user_partition` offset0、长度0x8000，READ_START/MIDST/END按固定长度与逐包边界收敛。拒绝写START/MIDST/END、擦除、重分区、任意地址和外部loader。
4. 完成后停止并关闭HOST句柄；离线验证GPT头/数组双CRC、分区边界、重叠与目标布局，用户正常开机观察单列。
5. 只有当前GPT可信后，另行准备1MiB uboot身份读取与备份对照。再安排当前system完整原件回读/哈希匹配及可恢复性验证，不直接跳到写入。

## system自足布局

已有v2.4.0原system完整1GiB文件，`06_Firmware/backups/v2.4.0-20260923-162730/p29-system.img`，SHA256 `6bf4706e5f03ed79edfe0e4ab337dbcc1310d6a7b57116a09ecfa756b4de648f`。此前verified清单及本日离线更新分析已核同一hash，本次未重复全量哈希。它不是完整整机恢复包，也未免ADB恢复实测。

本次只读1024字节ext4 superblock：4096字节块、free39440约154MiB；旧正式载荷约35.3MB。容量上有迁入静态app/media的余地，但这不是fsck或候选文件系统验收，不扩分区。

旧正式包把app/media放在p40 userdata的`/mnt/data/p011-toolbox/bili-formal/releases/...`，QRC入口也指向该路径；只刷旧Z03不构成完整安装。新候选应把不可变app/media放入system，独立启动项和QRC路径随之更新；首次启动只在每台笔自己的data区创建私有运行/缓存/账号目录。不得复制开发机userdata/NV补齐资产。

生成候选前还需确认镜像实际init/rc路径、data挂载时序与首次目录创建策略。继续保留原厂父循环，设置列表名称/图标/顺序/source仍为“用户反馈”；仅覆盖该页内容。冻结允许变化文件及整分区原件/候选完整hash，再讨论受控写入和回滚。

## 跨电脑分发

当前工具使用本机Python和已有SPRD驱动，尚不是便携安装器。项目没有独立完整的INF/CAT/SYS驱动包，也没有已核实的驱动再分发许可；资料索引中的单INF链接不能替代完整、可信、可分发来源。

短路径为固定版本/来源/hash的官方Windows x64嵌入式Python，配相对路径入口、隔离._pth和完整许可通知。当前wrapper通过sys.executable运行同目录脚本，直接冻结成单EXE会改变子进程与源码快照契约，需另行适配。用户无需自行装Python或ADB，但驱动首装仍需单独验证。

待写入/逐机备份恢复链完成后，在没有Python/ADB的干净Windows电脑验证驱动首装、版本拒绝、备份、写后全量回读、正常启动、原名入口/退出释放、重启和恢复。当前不得发布标为“免ADB正式可刷”的包。
