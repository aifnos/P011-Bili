# P011 B 站客户端

为碳氧 P011 学习笔适配的 B 站客户端。界面使用 Qt/QML，业务由笔端 Python 回环服务协调，B 站接口和播放器使用 C++。H.264 通过 GStreamer / OpenMAX 调用展讯硬解，H.265 和 AV1 通过 libmpv 软解。

## 源码

- [client/](working/BiliP011-v0.1/client/) 包含 QML 界面、接口适配、播放器及硬解进程。
- [formal/runtime/](working/BiliP011-v0.1/formal/runtime/) 包含原厂设置入口、回环会话服务和安装逻辑。
- [build/](working/BiliP011-v0.1/build/) 和 [formal/host/](working/BiliP011-v0.1/formal/host/) 包含 ARMv7 交叉编译及构建脚本。
- [架构说明](working/BiliP011-v0.1/client/ARCHITECTURE.md)记录早期客户端的分层和接口边界，[第三方来源](working/BiliP011-v0.1/THIRD_PARTY_NOTICES.md)列出依赖及许可。

## 实机状态与构建

归档记录中，基于 P011 v2.4.0 的 ADB 安装曾实测普通视频和短视频的画面与声音。密码登录仍有 -629，免 ADB 安装未完成整套实机验收。

这是源码发布。构建需要按脚本准备交叉编译环境、上游库、设备 ABI 和对应版本的原厂输入。仓库沿用 working/ 布局，并附上构建脚本引用的工具箱运行时和主机辅助源码。旧脚本引用固定版本的本地产物，需先重建前置组件并按实际路径配置。固件、专有库、账号数据、现场日志和安装包由本机环境保管。

客户端源码的许可见文件头与 [GPL 文本](LICENSE)。第三方组件遵循各自目录中的许可。学习笔的其他开发内容见 [P011 总仓库](https://github.com/aifnos/P011)。
