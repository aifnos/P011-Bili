# 内置 UNISOC 下载串口驱动

版本 `4.20.42.134`，INF 日期 2020-10-14，包含 `USB\VID_1782&PID_4D00`。本包仅使用 Windows x64 的 VCOM 文件组：`sprdvcom.inf`、`sprdvcom.cat`、`amd64/sprdvcom.sys`、`amd64/WdfCoInstaller01009.dll`，不含 ADB、调制解调器驱动或第三方安装器。

来源为 [CWHelper 固定提交](https://github.com/ColdWindScholar/CWHelper/tree/afdaf779a1981c8fedd21cb7198b4b706713f045/file/drive/SPD_Driver/Drivers/DriversForWin10/Drivers) 的公开镜像，不声称该仓库是 UNISOC 官方下载站。每个下载成员均核对固定 Git blob 标识，下载字节及安装字节 SHA-256 见 `driver-source.json`。没有从本机 DriverStore 导出文件作为来源。

镜像中的 INF 使用 LF；仅恢复 CRLF 后即得到目录签名中的原件。恢复后的 INF 与其配套 CAT/SYS/DLL 全部通过 Windows SDK SignTool `verify /kp`，INF/SYS/DLL 同时通过 `/c sprdvcom.cat` 成员校验，四项均退出 0、无警告。目录签名者为 Microsoft Windows Hardware Compatibility Publisher。原始下载的 INF 在 `source/driver-source-record.zip` 中保留，不用于安装。二进制和 INF 指令、硬件 ID、版本、版权均未修改。

UNISOC 驱动保留 UNISOC Communications Inc. 原版权，WDF 组件保留 Microsoft 原版权。镜像仓库 LICENSE 和 readme 作为来源记录保留；不将仓库 AGPL 许可套用于 UNISOC/Microsoft 驱动文件，也不宣称取得了新的厂商授权。

一键入口先校验本包及驱动文件，使用 Windows SetupAPI 和已发布 OEM INF 判断同版本是否已经注册。缺少时仅提权运行 Windows 自带 `pnputil /add-driver`，预装这一份签名 INF，由 Windows 在随后插入时按匹配优先级正常绑定。不传 `/install`、`/reboot`、卸载或强制选取参数，不关闭签名验证、不打开测试模式。驱动安装要求管理员权限；UAC 取消、安装失败、超时或需要重启时，本次不开始刷写。

此步骤只准备电脑驱动，不发送设备协议，也不表示 system 已刷入或实机验收通过。完整包仍待干净 Windows 的首次驱动安装、下载接口绑定以及 system 写入/启动/恢复验收。

实现依据：[Microsoft PnPUtil](https://learn.microsoft.com/en-us/windows-hardware/drivers/devtest/pnputil-command-syntax)、[SetupGetInfPublishedNameW](https://learn.microsoft.com/en-us/windows/win32/api/setupapi/nf-setupapi-setupgetinfpublishednamew)。
