# 第三方来源与通知

本开发运行时完整保留 Python Software Foundation 官方 ZIP 的 `LICENSE.txt`，路径为 `python-3.14.8-embed-amd64/LICENSE.txt`。该文件包含 Python 及随包组件的原始许可/通知；原 ZIP、官方 SPDX 和 Sigstore bundle 也均保留。不得因裁剪运行时或后续分发而删除这些通知。

Python 二进制、标准库 ZIP、DLL/PYD、`python.cat` 及 LICENSE 的原始成员长度、CRC 和 SHA-256 记录在 `manifest.json/upstream_members`，已配置目录记录在 `configured_runtime_members`。应用只修改私有 `python314._pth` 的固定搜索路径，原文件另存为 `.upstream`。没有修改 Python 源码或二进制，也没有给 Python、PSF 或 Microsoft 增加项目背书含义。

官方 SPDX 描述的组件包含 CPython、OpenSSL、libffi、Expat、zlib-ng、SQLite、zstd 等；组件详情以保留的官方 SPDX 和 LICENSE 为准。该 SPDX 多个依赖的 `licenseConcluded` 为 `NOASSERTION`，保留 SBOM 不等于本项目已经完成全部再分发法律审核。Windows C Runtime 相关通知与限制也应随原始 LICENSE 保留。

本目录不附第三方 USB 驱动。SPRD 驱动再分发许可、完整签名包及目标系统适用范围均未核实，状态为 `NOT_READY_REDISTRIBUTION_LICENSE_UNVERIFIED`；现有电脑安装过驱动不构成再分发许可。

本次没有添加字体文件、私钥、账号凭据、用户数据或设备 NV/校准数据。
