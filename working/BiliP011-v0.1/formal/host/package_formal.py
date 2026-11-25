"""Assemble a new local/private formal installer and hash every member."""
import argparse
import hashlib
import json
import pathlib
import shutil
import zipfile
from build_formal import build, FORMAL, BASE


def cmd(action):
    return ('@echo off\r\nchcp 65001 >nul\r\nsetlocal\r\n'
            'cd /d "%~dp0"\r\npython -B "%~dp0install_formal.py" ' + action + '\r\n'
            'set "P011_EXIT=%ERRORLEVEL%"\r\n'
            'if not "%P011_EXIT%"=="0" echo 操作未通过，请保留结果ZIP并查看日志。\r\n'
            'pause\r\nexit /b %P011_EXIT%\r\n').encode('utf-8')


README = '''# P011 B站正式写入包（本机私有）

入口固定为 **设置 → 用户反馈**。设置项名称、图标、排序、source不变，原反馈页内容被B站程序覆盖。

1. 解压到电脑本地目录，连接P011并打开root ADB。电脑需要现有Python 3和adb。
2. 双击“一键正式写入B站.cmd”。完成前保持供电和USB连接。
3. 安装完成后直接在笔上点“设置 → 用户反馈”进入B站，无需电脑启动，每次退出返回设置。
4. 需要恢复原反馈页时双击“一键恢复用户反馈.cmd”，账号、历史、偏好和版本备份均保留。

“仅检查不写入.cmd”只读核对设备；“校验安装包.cmd”只核对电脑上的包；“检查已安装状态.cmd”只读核对安装记录。
每次入口都在相邻目录生成原始日志、独立host/remote退出状态、result.json和结果ZIP。

支持对象严格限定已核验的v2.4.0固件 z031_v2.4.0-20251128_174826-user 和三项原厂文件SHA。
不是Android APK。检测到不同固件、多个目标、已有试验、原厂父循环异常、未知启动方式或包被修改时停止。
启动方式须在现场证明为systemd或/etc/inittab声明默认runlevel且调用/etc/init.d/rc的SysV。

这是明确的正式安装操作：先备份原厂Z03，再对/usr/bin/Z03做原子替换；只改内嵌SetUserReport.qml这一个QRC记录。
另写独立的B站服务启动项和私有运行文件，不编辑vendor启动脚本、control_engine、系统库、无线/NV/分区或USB配置。
若原ext4根挂载只读，仅在固定哈希等检查通过后为本次正式写入临时remount rw，finally恢复原挂载状态。
失败时按当前文件哈希精确回滚，保留原始错误和事务记录；不会强杀原厂UI、重启设备或删除用户数据。

正式服务空闲时仅监听127.0.0.1；打开页面才建立B站会话，退出/页面心跳超时回收播放器。
去掉旧10分钟试验总限；原生单次播放的480秒限制改为86400秒（24小时保护上限），页面保亮只跟随新鲜播放租约。
账号与偏好继续保存在设备原私有目录，不在安装包或结果ZIP中。

本包状态为HOST_BUILT_DEVICE_PENDING：电脑端构建、定点资源逆差、主机会话/异常/Qt编译检查通过。
制作时ADB无设备，尚未执行P011正式写入、开机启动、设置入口触摸、长时间播放及声音验收。
安装器的installed=true只证明固定文件/服务/进程检查；settings_navigation_verified和physical_acceptance仍为false。
旧切画质首帧偶发超时、弱网快滑、高画质预加载、满60fps等既有缺口没有在此包中声称修复。

本包含本机固件派生文件和私有媒体库，仅在本机使用，不是公开发行包或完整救砖镜像。
原备份不覆盖完整userdata等内容；一键恢复是指定文件恢复，不能当完整设备恢复证明。
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--native-dir', type=pathlib.Path, required=True)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    parser.add_argument('--evidence-dir', type=pathlib.Path)
    args = parser.parse_args()
    output = build(args.native_dir, args.output)
    shutil.copyfile(FORMAL/'runtime/device_install.py', output/'device_install.py')
    shutil.copyfile(FORMAL/'host/install_formal.py', output/'install_formal.py')
    for name, action in (('一键正式写入B站.cmd', 'install'), ('一键恢复用户反馈.cmd', 'restore'),
                         ('仅检查不写入.cmd', 'inspect'), ('校验安装包.cmd', 'verify'),
                         ('检查已安装状态.cmd', 'status')):
        (output/name).write_bytes(cmd(action))
    (output/'README.md').write_text(README, encoding='utf-8')
    # Explicit source/evidence copies; never walk original logs, account data,
    # firmware backups, private SDK files, fonts or unknown workspace folders.
    for folder in ('host', 'runtime', 'tests', 'native'):
        for source in sorted((FORMAL/folder).rglob('*')):
            if source.is_file() and source.suffix in ('.py', '.qml', '.cpp', '.hpp', '.h') and '__pycache__' not in source.parts:
                target = output/'source'/folder/source.relative_to(FORMAL/folder)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
    for name in ('build-result.json', 'source.diff', 'build.stdout.raw', 'build.stderr.raw'):
        source = args.native_dir/name
        if source.is_file():
            target = output/'evidence/native'/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    if args.evidence_dir:
        for source in sorted(args.evidence_dir.rglob('*')):
            if source.is_file() and source.suffix in ('.json', '.raw', '.txt'):
                target = output/'evidence/host'/source.relative_to(args.evidence_dir)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
    members = sorted(path for path in output.rglob('*') if path.is_file())
    manifest = ''.join(hashlib.sha256(path.read_bytes()).hexdigest()+' '+str(path.stat().st_size)+' '+path.relative_to(output).as_posix()+'\n' for path in members)
    (output/'PACKAGE.sha256').write_text(manifest, encoding='utf-8')
    archive = output.with_suffix('.private.zip')
    if archive.exists():
        raise ValueError('Archive exists; never overwrite a versioned package')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(output.rglob('*')):
            if path.is_file():
                bundle.write(path, path.relative_to(output).as_posix())
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise ValueError('Archive CRC failed')
        for path in output.rglob('*'):
            if path.is_file() and bundle.read(path.relative_to(output).as_posix()) != path.read_bytes():
                raise ValueError('Archive readback differs')
    print(json.dumps(dict(package=str(output), archive=str(archive),
                         archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                         archive_bytes=archive.stat().st_size,
                         files=len(members)+1, device_tested=False), indent=2))


if __name__ == '__main__':
    main()
