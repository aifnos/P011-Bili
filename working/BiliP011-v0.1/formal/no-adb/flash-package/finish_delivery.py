"""Offline handoff, root shortcuts, immutable ZIP copy and evidence archive."""
import hashlib
import json
import pathlib
import shutil
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[4]
NAME = 'P011-Bili-NoADB-v1-final-20261014'
PACKAGE = HERE / 'out' / NAME
REPORT = ROOT / '04_Documents/P011-Bili免ADB刷写包制作-20261014.md'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def main():
    assert ROOT == pathlib.Path('D:/project/P011')
    result = json.loads((HERE / 'final-package-result.json').read_bytes())
    target = ROOT / 'packages' / (NAME + '.zip')
    assert not target.exists()
    shutil.copyfile(PACKAGE.with_suffix('.zip'), target)
    assert sha(target) == result['zip_sha256']
    assert target.stat().st_size == result['zip_bytes']

    old = HERE / 'root-entry-before-no-adb'
    old.mkdir(exist_ok=False)
    links = {
        '一键正式写入B站.cmd': '一键正式写入B站.cmd',
        '一键恢复用户反馈.cmd': '一键恢复原系统.cmd',
        '校验免ADB刷写包.cmd': '校验刷写包.cmd',
    }
    for root_name, package_name in links.items():
        entry = ROOT / root_name
        if entry.exists():
            shutil.copy2(entry, old / root_name)
        assert (PACKAGE / package_name).is_file()
        relative = str((PACKAGE / package_name).relative_to(ROOT))
        entry.write_bytes(('@echo off\r\nchcp 65001 >nul\r\n'
            'call "%~dp0' + relative + '"\r\nexit /b %ERRORLEVEL%\r\n').encode('utf-8'))

    status = (
        '> 免ADB刷写包已制作（2026-10-14）：`P011-Bili-NoADB-v1-final-20261014.zip` '
        '位于项目 packages，144,923,039B，SHA256 `a8990f40cd38d3b5a7e1d9490268f576cea7001d044b5b61e61995d068666fbf`。'
        '新写入/恢复/校验入口、自带隔离Python、按设备备份和完整1GiB system写入/回读程序已打包；'
        '设置入口保留“用户反馈”原名。原/候选fsck、13,292原文件项比对、11项新HOST检查、'
        '实际全镜像差分重建、中文空格路径与ZIP全部成员读回通过。'
        '**状态HOST_PACKAGE_BUILT_VERIFIED_DEVICE_PENDING：本轮未操作设备，'
        '成品system刷入/启动/播放/退出/恢复及干净电脑驱动首装未验。** '
        '仅接受固定v2.4底包，电脑需已有厂商签名SPRD下载驱动。'
        '根写入和恢复入口现接此免ADB包；完整说明见 `04_Documents/P011-Bili免ADB刷写包制作-20261014.md`。'
        '下方“当前/未生成/拦截”等保留为当时历史阶段，不覆盖本条最新状态。\n\n'
    )
    documents = [
        ROOT / '01_Environment/00-项目交接与当前状态.md',
        ROOT / '01_Environment/02-工具版本与验证边界.md',
        HERE.parents[1] / 'NO_ADB_DISTRIBUTION.md',
        HERE.parents[1] / 'NO_ADB_NEXT_GATE.md',
        HERE.parent / 'README.md',
    ]
    for path in documents:
        source = path.read_text(encoding='utf-8-sig')
        assert '免ADB刷写包已制作（2026-10-14）' not in source
        heading, rest = source.split('\n', 1)
        path.write_text(heading + '\n\n' + status + rest.lstrip('\n'), encoding='utf-8')

    audit = ROOT / 'packages/P011-Bili-NoADB-host-evidence-20261014.zip'
    inputs = {p for p in HERE.iterdir() if p.is_file() and p.suffix in ('.py', '.json', '.raw', '.md')}
    for directory in ('image-build-20261014-v1', 'image-build-20261014-v2', 'image-build-20261014-v3', 'root-entry-before-no-adb', 'app'):
        inputs.update(p for p in (HERE / directory).rglob('*') if p.is_file() and p.suffix not in ('.img', '.pyc'))
    inputs.add(REPORT)
    inputs.add(PACKAGE / 'package-manifest.json')
    inputs.add(PACKAGE / '使用说明.md')
    inputs.update(ROOT / name for name in links)
    inputs.update(documents)
    manifest = {str(p.relative_to(ROOT)).replace('\\', '/'): {'bytes': p.stat().st_size, 'sha256': sha(p)} for p in sorted(inputs)}
    with zipfile.ZipFile(audit, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(inputs):
            bundle.write(path, str(path.relative_to(ROOT)).replace('\\', '/'))
        bundle.writestr('audit-manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(audit) as bundle:
        assert bundle.testzip() is None
        for name, row in manifest.items():
            data = bundle.read(name)
            assert len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256']
    delivered = {
        'scope': 'HOST_ONLY_NO_DEVICE', 'package': str(target), 'package_sha256': sha(target),
        'evidence_zip': str(audit), 'evidence_zip_bytes': audit.stat().st_size,
        'evidence_zip_sha256': sha(audit), 'evidence_members': len(manifest) + 1,
        'root_entries_wired': list(links), 'old_root_entries_preserved': str(old),
        'evidence_crc_and_all_members_sha_verified': True,
    }
    (HERE / 'delivery-result.json').write_text(json.dumps(delivered, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(delivered, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
