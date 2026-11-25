"""Portable fixed system installer/restorer. Import performs no USB operation."""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import shutil
import struct
import sys

from engine import Session, SIZES, require, sha_file
from gpt_readback import parse_primary

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE_SHA = '6bf4706e5f03ed79edfe0e4ab337dbcc1310d6a7b57116a09ecfa756b4de648f'
UBOOT_SHA = '3d8bfddf254aad299fe5b7d4f7f73cb0e94736c5e5c2f1e7407cba5688db11d0'
CANDIDATE_SHA = 'dd3dd7cd29ae6f7b741dd8b41495a01a254408c9ecf4b08e32aec554cdcaef4c'


def save_json(path, data):
    with pathlib.Path(path).open('x', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())


def verify_package(root=ROOT):
    manifest = json.loads((root / 'package-manifest.json').read_bytes())
    require(manifest['base_sha256'] == BASE_SHA and manifest['candidate_sha256'] == CANDIDATE_SHA,
            '安装包镜像身份不支持。')
    for name, row in manifest['files'].items():
        path = root / name
        require(not path.is_symlink() and path.is_file() and path.resolve().is_relative_to(root.resolve()) and
                path.stat().st_size == row['bytes'] and sha_file(path) == row['sha256'], '安装包文件损坏：' + name)
    return manifest


def layout(gpt):
    return [(p['index'], p['name'], p['first_lba'], p['last_lba'], p['size_bytes'], p['attributes'])
            for p in gpt['partitions']]


def apply_delta(original, patch, destination, expected_base=BASE_SHA, expected_candidate=CANDIDATE_SHA):
    require(pathlib.Path(original).stat().st_size == SIZES['system'] and sha_file(original) == expected_base,
            '原系统不匹配支持的完整底包，禁止套用补丁。')
    require(not pathlib.Path(destination).exists(), '候选文件已存在，拒绝覆盖。')
    # Validate the entire patch structure before creating the image.
    spans = []
    with pathlib.Path(patch).open('rb') as stream:
        require(stream.read(8) == b'P011DIF1', '补丁头损坏。')
        count_raw = stream.read(4)
        require(len(count_raw) == 4, '补丁计数缺失。')
        count = struct.unpack('<I', count_raw)[0]
        require(1 <= count <= 262144, '补丁数量异常。')
        previous_end = 0
        for _ in range(count):
            head = stream.read(12)
            require(len(head) == 12, '补丁区段不完整。')
            offset, size = struct.unpack('<QI', head)
            require(offset >= previous_end and offset % 4096 == 0 and 0 < size <= 1048576 and
                    size % 4096 == 0 and offset + size <= SIZES['system'], '补丁区段越界或重叠。')
            position = stream.tell()
            require(len(stream.read(size)) == size, '补丁数据不完整。')
            spans.append((offset, size, position))
            previous_end = offset + size
        require(stream.read(1) == b'', '补丁有未知尾部。')
    with pathlib.Path(original).open('rb') as source, pathlib.Path(destination).open('xb') as target:
        shutil.copyfileobj(source, target, 1048576)
    with pathlib.Path(patch).open('rb') as source, pathlib.Path(destination).open('r+b') as target:
        for offset, size, position in spans:
            source.seek(position)
            target.seek(offset)
            target.write(source.read(size))
        target.flush()
        os.fsync(target.fileno())
    require(sha_file(destination) == expected_candidate, '重建后的完整系统镜像不一致，禁止写入。')
    return len(spans)


def select_backup(root, identity, prodnv, gpt, expected_base=BASE_SHA):
    candidates = []
    for path in sorted(root.glob('*/backup-complete.json'), reverse=True):
        try:
            record = json.loads(path.read_bytes())
            image = path.parent / 'system.before.img'
            if (record['schema'] == 'p011.system-backup.v1' and record['device_identity'] == identity and
                    record['prodnv_sha256'] == prodnv and record['gpt_sha256'] == gpt and
                    record['system_sha256'] == expected_base and record['uboot_sha256'] == UBOOT_SHA and
                    image.is_file() and not image.is_symlink() and
                    image.stat().st_size == SIZES['system'] and sha_file(image) == expected_base):
                candidates.append(image)
        except (ValueError, KeyError, OSError):
            continue
    require(candidates, '未找到属于本设备且校验通过的完整原系统备份；停止恢复。')
    return candidates[0]


def execute(mode, output, root=ROOT, session_factory=Session):
    result = dict(status='NOT_COMPLETE', mode=mode, adb_invoked=False,
                  physical_acceptance=False, system_boot_verified=False, stock_radio_verified=False)
    session = None
    try:
        verify_package(root)
        require(shutil.disk_usage(root).free >= 6 * 1073741824, '本地可用空间不足 6 GiB。')
        session = session_factory(output)
        session.connect()
        before = pathlib.Path(output) / 'before'
        before.mkdir()
        gpt_sha = session.read_partition('user_partition', before / 'gpt.bin')
        gpt = parse_primary((before / 'gpt.bin').read_bytes())
        reference = parse_primary((root / 'data/reference-gpt.bin').read_bytes())
        require(layout(gpt) == layout(reference), '分区布局不同，停止。')
        require(not any(p['name'] in ('system_bak', 'system_a', 'system_b') for p in gpt['partitions']),
                '不支持的 system 副本或 A/B 布局。')
        hashes = {}
        for name in ('uboot', 'prodnv', 'miscdata', 'uboot_log'):
            hashes[name] = session.read_partition(name, before / (name + '.img'))
        require(hashes['uboot'] == UBOOT_SHA, '启动程序版本不匹配，停止。')
        misc = (before / 'miscdata.img').read_bytes()
        require(struct.unpack_from('<I', misc, 0x1004)[0] != 1, '检测到 root 标记状态，需专项核对后才能写 system。')
        identity = session.state['target_id_hash']
        backup_root = root / 'backups' / identity[:16]
        backup_root.mkdir(parents=True, exist_ok=True)
        if mode == 'install':
            backup = backup_root / pathlib.Path(output).name
            backup.mkdir(exist_ok=False)
            current = backup / 'system.before.img'
            current_sha = session.read_partition('system', current)
            if current_sha == CANDIDATE_SHA:
                result['status'] = 'ALREADY_INSTALLED_IMAGE_MATCHED'
                return result
            require(current_sha == BASE_SHA and sha_file(current) == BASE_SHA,
                    '当前完整 system 不匹配支持底包；备份保留，未写入。')
            for path in before.iterdir():
                shutil.copyfile(path, backup / path.name)
            save_json(backup / 'backup-complete.json', dict(schema='p011.system-backup.v1',
                device_identity=identity, prodnv_sha256=hashes['prodnv'], gpt_sha256=gpt_sha,
                system_sha256=current_sha, uboot_sha256=hashes['uboot'], system_bytes=SIZES['system'],
                created=datetime.datetime.now().astimezone().isoformat()))
            image = backup / 'system-bili.candidate.img'
            print('原系统完整备份已校验，正在重建 B站系统镜像。', flush=True)
            apply_delta(current, root / 'data/system.delta', image)
            expected = CANDIDATE_SHA
            result['backup'] = str(backup)
        else:
            image = select_backup(backup_root, identity, hashes['prodnv'], gpt_sha)
            expected = BASE_SHA
            result['backup'] = str(image.parent)
        save_json(pathlib.Path(output) / 'write-scope.json', dict(target='system', bytes=SIZES['system'],
                  sha256=expected, original_backup=result['backup'], mode=mode, device_identity=identity))
        # Persistent scope exists before the first destructive request.
        session.write_system(image, expected, (BASE_SHA, CANDIDATE_SHA))
        after = pathlib.Path(output) / 'after'
        after.mkdir()
        print('写入结束，正在完整回读 1 GiB system，请保持 USB 连接。', flush=True)
        observed = session.read_partition('system', after / 'system.readback.img')
        require(observed == expected and sha_file(after / 'system.readback.img') == expected,
                '写后全量回读不一致，停止；使用本设备原备份恢复。')
        result['system_readback_sha256'] = observed
        for name in ('user_partition', 'uboot', 'prodnv', 'miscdata', 'uboot_log'):
            reference_sha = gpt_sha if name == 'user_partition' else hashes[name]
            value = session.read_partition(name, after / (name + '.img'))
            require(value == reference_sha, '写后关联对象变化：' + name + '；保留证据，不自动修复。')
        result['status'] = 'SYSTEM_IMAGE_WRITTEN_AND_FULL_READBACK_VERIFIED'
        return result
    except BaseException as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
        print('已停止：' + result['error'], flush=True)
        return result
    finally:
        if session is not None:
            try:
                session.close()
            except BaseException as exc:
                result['status'] = 'NOT_COMPLETE'
                result['close_error'] = str(exc)
            result['transport'] = session.state
        save_json(pathlib.Path(output) / 'result.json', result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('install', 'restore', 'check'))
    parser.add_argument('--output', type=pathlib.Path)
    args = parser.parse_args()
    if args.mode == 'check':
        verify_package()
        print('安装包文件校验通过。未连接设备，未写入。')
        return 0
    require(args.output is not None and args.output.is_dir(), '缺少日志目录。')
    result = execute(args.mode, args.output)
    print('RESULT=' + result['status'], flush=True)
    if result['status'] in ('SYSTEM_IMAGE_WRITTEN_AND_FULL_READBACK_VERIFIED', 'ALREADY_INSTALLED_IMAGE_MATCHED'):
        if args.mode == 'install':
            print('串口已关闭。现在拔下 USB，正常开机；进入“设置 → 用户反馈”检查 B站入口。', flush=True)
        else:
            print('原 system 已完整恢复并回读一致，串口已关闭。请拔 USB 正常开机检查原反馈页。', flush=True)
        return 0
    if result.get('transport', {}).get('write_started'):
        print('写入已开始但未通过全部核对。请保留 backups，使用“一键恢复原系统.cmd”，不要删除备份。', flush=True)
    else:
        print('本轮未发送分区写入命令；原因和日志已保存。', flush=True)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
