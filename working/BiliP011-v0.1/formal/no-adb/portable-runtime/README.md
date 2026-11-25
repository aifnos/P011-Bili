# P011 便携开发运行时：仅 HOST 准备

状态：`HOST_RUNTIME_VALIDATED`。这是无需用户安装 Python 的 Windows x64 私有运行时，不是正式刷写安装器。驱动状态仍为 `NOT_READY`，完整免 ADB 写入、回读、启动及恢复链未在本目录中实现或验证。

## 固定来源与选择

- Python：**3.14.8，Windows x64 官方 embeddable package**，2026-09-30 发布。
- 官方发布页：https://www.python.org/downloads/release/python-3148/
- 活跃版本表：https://www.python.org/downloads/
- 原 ZIP：https://www.python.org/ftp/python/3.14.8/python-3.14.8-embed-amd64.zip
- SHA-256：`a93abe456ab01bd96d7a085b3cdb6566b3063f4241360d114142fbdb07f0a310`，与官方发布页及 SPDX 的 CPython 条目一致。
- 原 ZIP、官方 SPDX、Sigstore bundle、发布页和版本表 HTML 均保存在 `sources`；每次下载的 URL、最终 URL、时间相关响应头、长度和 SHA 保存在 `sources/download.records.json`。
- Sigstore bundle 已保留，本次没有安装签名验证工具或声称完成独立密码学验签。

选择仍接收维护二进制更新的 3.14 系列，未下载 3.12.10。官方 3.12.15 说明 3.12.10 是其最后完整二进制维护版本，不能把它当作后续正式分发的当前安全基础。这里选择的是当前 3.14 分支维护版，未声称它是所有 Python 分支中的最高版本。

## 目录与便携调用

`python-3.14.8-embed-amd64/python.exe` 为实际私有解释器。无需 pip、全局安装、修改 PATH 或注册 Python。保留整个 `no-adb/portable-runtime` 及上级 `no-adb` 脚本目录关系，移动到其他电脑时不使用本机用户名或固定盘符。

`python314._pth` 使用下列三条路径，保持 `import site` 关闭：

```text
python314.zip
.
..\..
```

三条路径分别指向随包标准库 ZIP、私有运行时 DLL/PYD 目录、上级 `no-adb` 脚本目录。上游 `python314._pth` 文件的完整字节保留在 `python314._pth.upstream`。唯一运行时配置变更是此搜索路径；原 ZIP、LICENSE 和二进制保持原样。

开发入口后续可使用相对自身位置的私有 `python.exe`，当前 `_child_command` 的 `sys.executable -u sibling.py` 契约已在新运行时下检查。此目录没有自动启动真实 core 的 CMD 或安装器。

## 本次验证与保留的失败

首次检查因为 `python314._pth` 中 `../..` 在本次 Windows 运行时下的实际路径不符合预期而失败。原始双流、退出码、首次 manifest 和结果 ZIP 均保留；没有改判该失败。配置改为 Windows 反斜杠 `..\..` 后，新的首次兼容检查通过。

通过范围：版本/64 位指针、隔离 flags、精确三条搜索路径、伪造 `PYTHONHOME/PYTHONPATH` 不生效、ctypes 结构 ABI、json/zlib/SSLContext、本地 ZIP CRC、六份源码 compile-only，以及既有包装器的命令构造/文件锁/固定 Fake child 双流与 ZIP SHA/CRC。源文件前后 SHA 相同。

没有调用 `inventory`、打开串口、运行真实 core、连接网络服务或 P011；没有重跑旧专项。`build-result.json` 指向当前通过日志 ZIP，`build-result.first-failed.json` 指向原失败；每份结果都保留独立原始 stdout、stderr、host exit、timeout 和不适用的 remote exit。

## 仍未就绪

驱动状态见 `DRIVER_STATUS.json`：独立 SPRD 驱动安装包、完整签名文件组及再分发许可均未核实，禁止从本机 DriverStore 导出后冒充可分发来源。此目录未安装驱动。

当前只在本开发 Windows x64 主机验证，尚未做没有 Python 的干净 Windows 电脑首装验收。其他架构、Windows 版本、系统 C Runtime 和驱动首次安装仍需在分发范围确定后验证。完整许可与第三方说明见 `THIRD_PARTY_NOTICES.md` 及运行时原始 `LICENSE.txt`。

## 重建

`build_runtime.py` 是开发主机的一次性 HOST 构建助手，拒绝覆盖既有 sources/runtime/manifest。需要重建时使用新的版本化工作目录，保留此目录证据；终端用开发 Python 执行该助手不会安装任何组件。打包给用户的成品不需要用户运行此构建助手。
