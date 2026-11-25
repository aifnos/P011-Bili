# P011 下载模式原件写回试验

这是开发阶段的固定目标试验，不是 B站用户分发安装器。当前仅支持这台开发电脑已核对的 SPRD 驱动与固定版本 x86 `spd_dump.exe`；不存在 ADB 调用。

## 固定范围

- `read_preflight.py`：从关机拔线开始，等待新接口，执行内置 AutoD 初始化；读取当前主 GPT、uboot、miscdata、uboot_log 和两份完整 sysdumpdb。校验主 GPT CRC、布局及固定大小。原生子进程只收到固定读命令，完成后停止该进程。
- `sysdump_original_rewrite.py`：只续接同一笔的已建立 FDL2 会话。唯一允许的写目标是 sysdumpdb，长度 10,485,760 字节，内容必须是刚刚取得的两份一致原件。写前重读五个对象；START 一次、MIDST 2560 次、END 一次；写后重读五个对象逐字节比较。
- `run_sysdump_rewrite.py`：进程锁、600 秒父期限、精确子进程关闭、双原始输出流、源码快照及 ZIP CRC/SHA 回读。父进程本身不打开设备。

每次协议请求先消耗尝试次数，再调用 WriteFile；部分写、超时、坏校验、拒绝应答及身份变化均停止，不重发、不自动 END、不擦除、不重分区、不自动修复。没有修改原握手传输类的 TX 白名单。

`approval_for()` 生成的 scope 文件是用户本轮已授权试验的机器可校验范围记录，不是另一个用户批准来源。记录绑定当前备份、完整 sysdumpdb GPT 项、设备身份、COM 和源码 SHA。持久 `.original-rewrite.claim` 在打开串口前排他创建，同一份原件试验不能重跑。历史 claim、失败和原始日志不得删除来绕过限制。

BOOT 重枚举的 CONFIGRET 13 仅在尚未进入 FDL2 时允许最多连续两秒观察等待；这不产生合格设备清单。分区阶段节点消失仍立即停止。

## 证据解释

`ORIGINAL_REWRITE_ACK_AND_READBACK_MATCHED` 仅表示固定目标完整 WRITE 命令链的应答和完整回读一致。同字节写回不能排除设备忽略相同内容，因此不证明改变位真正持久化；也不证明 system 修改镜像接受、B站安装、正常开机、用户功能恢复或跨电脑分发。

读取/写入关闭后的正常开机由用户实际观察单列，不能改写原协议 result 的历史 `physical_restoration_verified=false`。

原件、回读、原始协议日志和 ZIP 均为本机私有诊断资料，不打包给其他笔刷入。完整 sysdumpdb 原件不是整机恢复镜像。

## HOST 验证

`test_read_preflight.py` 使用本机假子进程覆盖固定读计划、短读停止、正常系统接口拒绝、启动节点短暂消失及 FDL2 节点丢失停止。

`test_sysdump_original_rewrite.py` 使用内存设备覆盖完整 2560 块回写和读取、START 拒绝、数据应答校验失败、写前内容变化和 Windows 短写只尝试一次。它们均不是实际设备试验；实际结果见项目 `04_Documents` 的独立报告。

协议依据固定上游 [common.c](https://raw.githubusercontent.com/TomKing062/spreadtrum_flash/2a202404a7512026d146b62624f089aceb408520/common.c) 的普通命名分区读取与普通 START/MIDST/END 分支。
