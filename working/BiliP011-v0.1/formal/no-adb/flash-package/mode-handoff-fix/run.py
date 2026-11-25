"""Portable user entry with lock, exact child, raw streams and evidence ZIP."""
import argparse
import datetime
import hashlib
import json
import pathlib
import sys
import uuid
import zipfile

from flash import ROOT, verify_package
from run_early_mode_probe import ExclusiveLock, _capture
from driver_setup import ensure_driver


def archive(output):
    included = []
    for path in sorted(output.rglob('*')):
        if path.is_file() and not path.is_symlink() and path.suffix != '.img' and path.name != 'gpt.bin':
            included.append(path)
    result = output.with_suffix('.zip')
    hashes = {}
    with zipfile.ZipFile(result, 'x', zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as bundle:
        for path in included:
            name = path.relative_to(output).as_posix()
            digest = hashlib.sha256()
            with path.open('rb') as source, bundle.open(name, 'w', force_zip64=True) as target:
                for chunk in iter(lambda: source.read(1048576), b''):
                    target.write(chunk)
                    digest.update(chunk)
            hashes[name] = digest.hexdigest()
        bundle.writestr('archive.manifest.json', json.dumps(hashes, indent=2))
    with zipfile.ZipFile(result) as bundle:
        if bundle.testzip() is not None:
            raise RuntimeError('结果 ZIP CRC 检查失败。')
        for name, expected in hashes.items():
            with bundle.open(name) as stream:
                digest = hashlib.sha256()
                for chunk in iter(lambda: stream.read(1048576), b''):
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                raise RuntimeError('结果 ZIP 读回不一致。')
    return result


def workflow(mode, output):
    code = ensure_driver(output / 'driver')
    if code:
        return code
    if mode == 'driver':
        print('驱动准备完成；没有连接或刷写设备。')
        return 0
    print('安装入口：设置 → 用户反馈（保留原名）。恢复只使用本设备保存的原 system。')
    print('请先正常关机并拔下 USB。保持未插，按回车后等待“接口已就绪”提示再插入。')
    input()
    command = [sys.executable, '-B', '-X', 'utf8', '-u', str(ROOT / 'app/flash.py'), mode, '--output', str(output)]
    (output / 'command.json').write_text(json.dumps(command, ensure_ascii=False, indent=2), encoding='utf-8')
    # A 3h absolute bound includes original read, full write and readback.
    status = _capture(command, output, 10800)
    (output / 'host.status.json').write_text(json.dumps(status, indent=2), encoding='utf-8')
    if status['interrupted']:
        return 130
    if status['timeout']:
        return 124
    if (status['capture_errors'] or status['stdout_forward_errors'] or status['spawn_error'] or
            status['termination_error'] or not status['streams_complete']):
        return 1
    return status['host_exit'] if status['host_exit'] is not None else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('install', 'restore', 'check', 'driver'))
    args = parser.parse_args()
    print('P011 B站下载模式刷写包 v6 / Windows x64 / 完全不使用 ADB', flush=True)
    print('下载初始化、分区表及 uboot 读取已实机通过；system 写入与开机尚未验收。', flush=True)
    verify_package()
    if args.mode == 'check':
        print('安装包校验通过；没有连接设备。')
        return 0
    logs = ROOT / 'logs'
    logs.mkdir(exist_ok=True)
    with ExclusiveLock(ROOT / '.flash.lock'):
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        output = logs / (stamp + '-' + args.mode + '-' + uuid.uuid4().hex[:8])
        output.mkdir(exist_ok=False)
        try:
            return workflow(args.mode, output)
        finally:
            result = archive(output)
            print('私有日志 ZIP：' + str(result))
            print('原备份保存在 backups；不要把设备备份或日志放进分发包。')


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print('无法继续：' + str(exc), file=sys.stderr)
        raise SystemExit(1)
