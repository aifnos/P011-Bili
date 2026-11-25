# 免ADB用户分发要求与当前可行性

> v6模式交接修订及冷启动实测（2026-10-14）：用户v5已恢复一次CreateFileW433并发送MODE，但强制观察重枚举超时；未发SYNC或分区命令。v6保留MODE后旧句柄被动读取窗口，处理限定阶段的旧句柄失效，允许同节点沿用，仍以精确协议应答确认AutoD。30项HOST通过；实机冷启动初始化、GPT32KiB和uboot1MiB读取通过、基线SHA一致、277次TX/276帧RX离线复核、MODE及初始SYNC各1、无分区写入、HOST0/句柄关闭，用户确认原厂开机。正式包engine与本轮实测完全相同；system写入/修改镜像启动/B站/恢复和干净电脑仍待。新包 `packages/P011-Bili-NoADB-v6-handoff-20261014.zip`，SHA256 `da00e7f0c48a3abb553b8fa81303984bf12d11305b5d994614da98b7d0d1b1ac`；用户原目录旁已有v6，根入口已切换。详见 `04_Documents/P011-Bili模式交接修订与冷启动读取实测-20261014.md`；以下为历史。

> v5串口打开修订（2026-10-14）：用户v4首次节点已就绪，但打开/初始化报告WinError433；MODE/SYNC/写入均0，原wire TX/RX为0字节，旧日志不足以定位具体API。本版在已确认失败句柄关闭、同设备身份及协议未尝试条件下限时重新识别打开；禁止重发MODE、SYNC和分区命令，新增API/错误码/关闭结果/调用栈证据。48项HOST检查、用户中文路径校验和ZIP全成员核验通过。新包 `packages/P011-Bili-NoADB-v5-open-20261014.zip`，SHA256 `2613d7d46222d78310e2feda99814c6c4b152e15c63c4e149be7c61722cfbbfa`，原用户目录旁已有v5，根入口已切换。真实433恢复、system及干净电脑验收仍待；本轮无设备命令或驱动安装。详见 `04_Documents/P011-Bili串口打开生命周期修订-20261014.md`；以下为历史。

> v4首次就绪修订（2026-10-14）：用户v3停止于首次节点未就绪，open/MODE/SYNC/写入均0，原wire TX/RX为0字节；驱动包已注册，原日志未保存具体未就绪字段。补齐同实例首次启动/COM分配的3秒限时观察，持续异常报告实际状态，保留v3模式后重枚举和存储断连拒绝。8项新HOST＋1项受影响完整模拟连接、用户中文路径校验和ZIP成员校验通过。新包 `packages/P011-Bili-NoADB-v4-ready-20261014.zip`，SHA256 `c6f3cf342f42fb8ed5d27e26827d29b885fef4327a836560002effad7591937c`，原用户目录旁已有v4、根入口已切换。system设备验收仍待，本轮无驱动安装或设备命令。详见 `04_Documents/P011-Bili首次接口就绪等待修订-20261014.md`；以下为历史。

> v3重枚举修订（2026-10-14）：用户v2原始TX只有一次MODE、RX只有回显，无实际SYNC/分区命令，原失败保留。修正MODE后固定0.5秒即重开句柄的时序缺口，改为单次MODE后限时观察同一设备重枚举并稳定；存储断连/多设备/身份变化仍拒绝。8项新HOST和用户中文路径纯校验通过。新包 `packages/P011-Bili-NoADB-v3-reenum-20261014.zip`，SHA256 `4cee68335a5038714865ab8ca42b7853645566a70c4eb627aabb6e16ad4159e4`；原使用目录旁已有v3，根入口也已切换。设备初始化及system实机验收仍待，本轮未操作设备。详见 `04_Documents/P011-Bili下载接口重枚举修订-20261014.md`。以下为历史阶段。

> 含驱动免ADB包已制作（2026-10-14）：`packages/P011-Bili-NoADB-v2-driver-final-20261014.zip`，144,585,149B，SHA256 `682b2a8825f3af8e728e66bb58100d30780a6dba2a0b4888084e8b5e5c8590d4`。内置与此前实测一致的UNISOC VCOM 4.20.42.134，CAT和INF/SYS/DLL签名全过；写入/恢复前自动检查，缺少则经Windows UAC预装，已安装跳过，失败或要求重启时停止。10项新HOST检查、修正OEM INF路径后的本机只读识别、中文空格路径/隔离运行时和ZIP全成员验证通过。system载荷未改，复用v1已过证据。**仍待干净PC驱动首装和system实机写入/启动/功能/恢复，本轮没有驱动安装或设备操作。** 根入口已接v2，增加单独驱动入口；详见 `04_Documents/P011-Bili免ADB含驱动刷写包-20261014.md`。以下无驱动/未生成等为历史阶段。

> 免ADB刷写包已制作（2026-10-14）：`P011-Bili-NoADB-v1-final-20261014.zip` 位于项目 packages，144,923,039B，SHA256 `a8990f40cd38d3b5a7e1d9490268f576cea7001d044b5b61e61995d068666fbf`。新写入/恢复/校验入口、自带隔离Python、按设备备份和完整1GiB system写入/回读程序已打包；设置入口保留“用户反馈”原名。原/候选fsck、13,292原文件项比对、11项新HOST检查、实际全镜像差分重建、中文空格路径与ZIP全部成员读回通过。**状态HOST_PACKAGE_BUILT_VERIFIED_DEVICE_PENDING：本轮未操作设备，成品system刷入/启动/播放/退出/恢复及干净电脑驱动首装未验。** 仅接受固定v2.4底包，电脑需已有厂商签名SPRD下载驱动。根写入和恢复入口现接此免ADB包；完整说明见 `04_Documents/P011-Bili免ADB刷写包制作-20261014.md`。下方“当前/未生成/拦截”等保留为当时历史阶段，不覆盖本条最新状态。

> 最新下载模式实测（2026-10-14）：sysdumpdb 10 MiB 原件双备份、单次完整写回与完整回读通过，WRITE START/MIDST/END 为 1/2560/1 且全部 ACK；GPT、uboot、miscdata、uboot_log 写前后逐字节一致，原始 TX/RX 10790 对离线复核通过。全程无 ADB，writer/parent exit0、句柄关闭，用户确认拔线后正常进入原厂主界面。仅签原件写回应答和回读一致，不证明改变位持久化、system 修改镜像接受、B站安装、完整恢复或跨PC分发。原失败和旧证据保留，详见 04_Documents/P011-下载模式原件写回实测-20261014.md；以下为历史阶段。

> 最新现场结果（2026-10-14）：19:47固定本轮证据的无MODE续接，在新句柄发送1次SYNC后收到精确20字节AutoD版本，1次空CONNECT后收到8字节CRC16 ACK；已确认`AUTOD_HANDSHAKE_CONFIRMED_NO_STORAGE_ACCESS`。全轮累计MODE1/SYNC1/CONNECT1，无ADB/loader/EXEC/内存/分区操作，HOST句柄关闭true、child/wrapper exit均0。续接结果：`evidence/autod-continuation-20261014-194759-629465-9b793455.zip`，SHA256 `b15794ea489edf5aaf2308817830894f0169e4eb4edd113d2cf47382217aa7fc`。原WinError22失败保持；用户随后报告“已正常进入原厂主界面”，**正常开机回到原厂主页的用户观察已确认**，不代替原厂文件哈希、无线或完整业务恢复验证。写入、目标回读、修改镜像启动及跨电脑便携包仍未验证，当前仍为`NO_ADB_WRITE_PATH_NOT_VERIFIED`。

更新：2026-10-14。用户明确要求：**必须完全不依赖ADB，安装包要分发到不同电脑给用户使用。**

> 后续实现进度（20:12）：system自足布局候选7d8e33be09953969b7670025已生成并首次HOST检查通过；固定存储读取codec/阶段门、32KiB GPT离线校验与独立便携Python运行时也已完成各自HOST检查。未生成完整system候选镜像、未整合完整存储客户端、未进行新设备读写，驱动分发仍NOT_READY。详见`04_Documents/P011-免ADB一键包实现进度-20261014.md`；正式写入能力状态保持未验证。

> 后续离线核对：已有完整1GiB原system基线，历史内置AutoD阶段有存储读取证据，但本机写保护/修改镜像接受和免ADB恢复未验。旧正式包的静态app/media位于userdata，需重做system自足布局，保留每台设备自己的data/NV；项目也缺完整可分发驱动与便携runtime。下一阶段固定32KiB GPT读取及实现门见[后续边界](NO_ADB_NEXT_GATE.md)，尚未执行新的存储阶段。

> 首轮接口实测历史（19:38）：已捕获新4D00 COM9并发送单次已授权MODE，写API返回，随后WinError22而停止；HOST句柄关闭true、SYNC0/CONNECT0、AutoD/ACK未确认。无ADB/loader/内存/分区动作，物理恢复未验。原失败ZIP：`evidence/early-mode-probe-20261014-193756-572489-4d25b551.zip`。后置PnP仍4D00，当时无MODE续接正在离线准备；以下“尚未运行”均为此前准备阶段历史状态，不将这一MODE返回当可刷证明。

当前状态：**NO_ADB_WRITE_PATH_NOT_VERIFIED**。现有 `P011-Bili-Formal-v1-final-20261014.private.zip` 依赖root ADB和电脑已有Python/adb，不能作为满足本要求的用户分发版。保持该开发包和历史证据原样，不把移植/改名视为免ADB支持。

项目根目录`一键正式写入B站.cmd`现已拦截旧ADB开发入口：只显示免ADB写入通道尚未实机验证的说明，以HOST退出码2结束，不连接或写入设备。历史`out`开发包、ZIP与恢复入口保持原样；根入口的拦截只防止误启动旧写入流程，不表示免ADB安装已经完成，也不使历史开发ZIP变成可分发版本。

## 已核实与未核实

- 历史P011早期USB接口曾返回SPRD4:AutoD并完成空CONNECT，已有GPT和选定分区读取记录。这是一条不依赖正常系统ADB的候选通道，但没有对应修改镜像写入、写后回读、启动和恢复实测。
- v2.4.0系统镜像离线发现原厂SWUpdate与update-recovery脚本。脚本查找ota.swu，传入硬件标识与公钥；对system内swupdate的ARM反汇编进一步确认，无公钥参数会失败，解析前无条件验证sw-description.sig，EVP_DigestVerifyFinal失败直接拒绝。该系统升级器有强制签名门，现有材料没有制作原厂有效签名的能力；未将system二进制结论外推未单独审查的recovery镜像。
- 原厂root ADB、GPT存在、vbmeta文件全零均不能单独证明下载模式允许任意镜像或修改系统可启动。
- 2026-10-14早前Windows只读PnP检查未发现P011相关USB接口。用户随后连接设备，当时可见正常系统1782:4064。新50ms级只读枚举记录器的首个60秒窗口未见拔出或4D00，历史结果RUNTIME_ONLY_NO_DOWNLOAD_INTERFACE；该窗口未调用ADB、打开串口、执行旧脚本或写设备，当时等待正确启动阶段捕获。后续实测单列页首，不追改这份观察记录。详见`no-adb/README.md`与`evidence/usb-no-adb-20261014-183451-519803.zip`。
- 既有备份是部分/在线快照，含本机NV和校准；不得把整份个人备份发给其他用户或当作通用恢复包。

## 本轮新增的免ADB受限握手候选

本节保留2026-10-14离线实现阶段的动作边界，保留上方纯观察结果与全部历史证据，不把HOST测试写成现场PASS。`no-adb/early_mode_probe.py`与`no-adb/win32_download_transport.py`提供独立的启动阶段模式选择及握手候选；`no-adb/run_early_mode_probe.py`的stdout/stderr/退出/结果ZIP封装入口已完成三项Fake child首测，并有进程锁、总期限、源码SHA与ZIP读回。**“实际设备轮次尚未运行”是准备阶段历史状态**，后由页首首轮失败和续接实测更新。原`Capture-P011Usb.ps1`和`capture_usb_host.py`纯观察器保持可追溯，归档脚本不自动执行。

新增`no-adb/continue_autod_handshake.py`与`no-adb/run_continue_autod.py`只针对19:38这轮固定证据，核验原件/SHA/剩余预算/目标身份后以独占claim限定1次无MODE续接；该claim已在19:47实测消耗。续接使用新句柄重新获得版本和ACK，无分区功能，不是通用重试、用户刷入包或再次试验指南。

候选只等待本轮新出现、唯一、started且problem=0的`1782:4D00` COM接口，打开后和发送前再次核对精确身份与活句柄。启动时已有4D00、多个下载接口、正常系统4064与下载接口共存或身份不明均拒绝。正常系统`1782:4064`的DIAG/AT/LOG等接口只可枚举，永不打开，不接收BSL发送。

允许发送的完整预算是**最多1次MODE/4次SYNC/1次CONNECT**，写API失败或短写也消耗尝试，不自动重发：

- MODE为`7E 00 00 00 00 08 00 FE 82 7E`，是主动启动模式选择，可能改变启动状态、重启或使屏幕保持黑屏；需要显式启用`--permit-mode-selection`，不得称为被动读取。
- SYNC为单字节`7E`，最多4次、间隔至少400ms，仅在MODE写API已返回、当前无待读数据/半包的版本等待阶段允许。
- 空CONNECT为`7E 00 00 00 00 00 00 7E`，只由同一活会话完整、无杂质、CRC16正确的精确`SPRD4:AutoD\0`版本授权；008B错误、ACK或其他版本不能授权。句柄丢失后必须重新验证版本。确认空ACK后即停止。

串口打开会配置115200/8N1、DTR/RTS及超时；MODE/CONNECT可能改变临时会话。因此该候选是有主动动作的受限握手工具，不能归入纯观察器。它不调用ADB、不上传外部loader/FDL，不发送EXEC_DATA、内存、分区读写、擦除、解锁、reset或固件升级命令，不触碰系统文件、启动脚本、WCN/NV或用户数据。这里描述的是HOST发出的动作边界，不推定设备内部绝无日志变化。

**准备阶段历史记录为“新候选实际设备轮次尚未执行”；最新已确认AutoD握手，用户随后报告“已正常进入原厂主界面”。** HOST解码/模拟测试、PnP枚举、串口打开、MODE写API返回、AutoD版本、CONNECT ACK与用户恢复观察继续分开记录。当前ACK已验证，协议结论只到`AUTOD_HANDSHAKE_CONFIRMED_NO_STORAGE_ACCESS`；正常开机回到原厂主页的用户观察单列。原始`result.json`的`physical_restoration_verified=false`反映协议记录当时未获用户反馈，保持历史字段不变。用户观察不代替原厂文件哈希、无线或完整业务恢复验证。

此候选**只是开发握手工具，还不是用户一键刷入包**；它没有增加分区写入/回读能力，没有完成修改镜像接受、启动或恢复验证，也没有满足跨电脑免Python/免ADB便携分发要求。设置入口仍按已确认需求保留“用户反馈”原名，后续正式安装验收另行完成。具体状态机、超时和日志边界见`no-adb/README.md`。

## 免ADB版本的实现门槛

1. 先用一台测试笔核实非ADB USB通道、阶段、精确固件/分区身份以及只读能力，不先执行写入。
2. 确定可信且匹配P011的写入方式和镜像接受条件，避免借用其他机型loader或依据芯片相似推定兼容。
3. 确定最小写入集合。现Bili资源在数据区；免ADB若只能写裸分区，需要另行安排只读系统资产与每台设备自己的运行/账号数据。不能把开发机userdata整体刷给用户。
4. 冻结原镜像、候选镜像与具体逆差；每台用户设备自行备份自己的必要原件，先确认可实际恢复。未知版本/布局/校验必须拒绝。
5. 在测试笔完成受控写入、全部目标读回、正常启动、设置“用户反馈”名称和进入/退出、正常重启后入口及恢复验证。原厂业务/无线与用户数据保持单列核验。
6. 再制作Windows便携分发程序：无需用户安装Python或adb，不带开发机绝对路径，不固定COM号；包含明确可分发的工具/驱动及依赖，目标选择、版本识别、恢复与日志ZIP均在新电脑验证。

以上是要求和门槛，不是已具备功能。目前不生成或分发标为“免ADB可刷”的文件，也不以PC离线生成镜像替代设备写入与恢复证据。

## 可追溯依据

- `02_Tools/backup-protocol/P011-AutoD-ReadPartitionList.ps1`：内置AutoD、固定读分区表，无外部FDL/PAC/写擦/解锁。
- `02_Tools/backup-protocol/P011-AutoD-BackupFirmware.ps1`：固定只读分区白名单。
- `04_Documents/original-reports/P011-BootSelect-v13-original-report.txt`：早期接口、握手及无存储操作边界。
- `04_Documents/original-reports/P011-GPT-核对报告.txt:14`：GPT不证明解锁、安全启动关闭或ADB开启。
- `formal/no-adb-analysis/offline-update-20261014`：v2.4.0只读系统镜像定点提取与升级机制证据。
- [SWUpdate官方签名机制](https://sbabic.github.io/swupdate/signed_images.html)：签名描述和子镜像SHA验证，编译启用签名后不能在运行时关闭。P011本轮system二进制强制验签已静态确认，其他恢复分支/现场行为未实测。
- [spreadtrum_flash作者说明](https://github.com/ilyakurdyukov/spreadtrum_flash/blob/main/README.md)：通用工具的分区写入能力与匹配loader要求，不是P011兼容性证明。
