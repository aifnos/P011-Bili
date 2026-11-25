# 第三方来源与本地交付边界

这是 P011 本地开发/临时验收适配，不是上游 wiliwili 官方版本、原厂固件或公开二进制发行。没有捆绑字体，也不在源码/结果 ZIP 中包含 Z03、Mali、原厂系统库、账户目录、二维码或私有链接 sysroot。

## 源码与依赖

|组件|来源/版本|保留的许可证/说明|
|---|---|---|
|P011 Bili C++/QML 适配|本目录 client、bridge、runtime、host、build|新源文件 SPDX GPL-3.0-or-later；上游 GPL-3.0 全文随源码包保留|
|wiliwili 参考与依赖来源|xfangfang/wiliwili `88e5876bea9502d06f46a8656e3530684d3aaf7d`|GPL-3.0；未把完整桌面 UI 当作本机实现，未导出上游字体|
|nlohmann/json|随固定上游的 3.11.2 单头文件|MIT；保留 Niels Lohmann 版权与许可证|
|QR Code generator|固定上游 QR-Code-generator/cpp|Project Nayuki MIT；保留 cpp/hpp 文件内完整 notice|
|stb_image_write|固定上游 glfw/deps，v1.16|保留文件内 MIT / public-domain 双许可全文|
|Rime 简体拼音词库|`0c6861ef7420ee780270ca6d993d18d4101049d0`|Apache-2.0、AUTHORS、原 YAML、转换脚本与 SHA-256；转换仅调整表示/排序并限制候选数|
|CPython JSON stdlib|v3.5.10，兼容笔端 3.5.5|PSF LICENSE 包含在 stdlib-json35.zip；文件锁定哈希保留|
|mpv|0.36.0|源码中的 LICENSE.GPL、LICENSE.LGPL；具体构建选项见 build/build_deps.py|
|FFmpeg|6.1.6|源码 LICENSE.md 和 GPL/LGPL 文本完整保留；具体启用组件见构建脚本|
|dav1d|1.5.3，VideoLAN官方源码镜像标签|BSD-2-Clause的COPYING及源文件版权保留；AV1的ARMv7/NEON软件解码，不冒称本机AV1硬件解码|
|GStreamer / gst-plugins-base 公共头文件|1.14.2，gstreamer.freedesktop.org 原始发布包|LGPL-2.0-or-later及原始COPYING/notice保留；仅编译独立自有工作进程，运行链接设备既有GStreamer，不打包原厂库；原始下载SHA-256进入构建来源锁|
|FreeType|2.13.3|LICENSE.TXT、docs/FTL.TXT 及源码 notices；没有导出字体|
|HarfBuzz / FriBidi / libass|8.5.0 / 1.0.17 / 0.17.5|各源码 COPYING 和源文件 notices|
|OpenSSL / curl|3.5.8 / 8.22.0|各源码 LICENSE.txt / COPYING|
|SDL 最小 ARM 配置头|固定上游 SDL_config_minimal.h|保留头文件 notice；运行使用设备已有 SDL，不把原厂 SDL 复制进交付包|
|私有SDL窗口握手实验|SDL 2.0.8官方源码；`third_party/SDL2-2.0.8-p011`|zlib/COPYING保留；P011-CHANGES.md明确标记修改。有界500ms真实configure等待，仅新实验媒体携带自编译SDL，不覆盖系统库；默认46df仍用原厂SDL|
|Wayland主机scanner及公共协议头|1.14.0发布源码；构建容器wayland-protocols 1.25|原MIT许可与notice保留；仅生成与设备旧ABI兼容的代码，不向笔分发主机程序或另一个Wayland运行库|
|交叉编译器与 GCC 运行库|Bootlin ARMv7 hard-float 2018.07-3 / GCC 8.2 / glibc 2.27|SDK 下载 URL、SHA-256 固定在 build/Dockerfile；与 GCC Runtime Library Exception 等材料分开管理，不声称项目源码 ZIP 包含完整编译器源码|

自编译依赖（本轮新增dav1d）的实际下载来源和 SHA-256 来自构建卷 `/work/p011/sources-lock.json`。`build/export_sources.py` 从与锁匹配的源码树制作源码快照，保留许可证，并排除测试字体、嵌套压缩测试资源、二进制和链接；所选构建关闭这些字体测试。完整原始源码仍在本机 Docker 构建卷，源码锁可用于复核原始下载。

## 交付内容

- 本地源码包包含适配源码、构建/测试脚本、上述实际使用的头文件/词库/JSON stdlib、许可证、来源锁及依赖源码快照，不包含原厂副本或任何运行时二进制。
- 实机安全结果包由固定白名单产生，只包含技术状态、公开页面截图及固定事件；个性化关注列表、账号页、二维码不截图。
- 一键验收入口只使用该工作区内已有并校验过的媒体导出与用户本机 v2.4.0 原厂备份来生成新临时候选；源码包本身不是可脱离工作区刷入的固件。
- 若以后要公开分发含 GCC 运行库或其他二进制的安装包，需另行整理与该发行物精确匹配的工具链对应源码/许可材料及第三方分发边界。本次不进行公开发布。
