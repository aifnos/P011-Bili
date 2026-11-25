"""Append latest state and archive driver-specific host evidence, no device IO."""
import hashlib
import json
import pathlib
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[4]
REPORT = ROOT / '04_Documents/P011-Bili免ADB含驱动刷写包-20261014.md'
RESULT = json.loads((HERE / 'driver-package-result.json').read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    status = (
        '> 含驱动免ADB包已制作（2026-10-14）：`packages/P011-Bili-NoADB-v2-driver-final-20261014.zip`，'
        '144,585,149B，SHA256 `682b2a8825f3af8e728e66bb58100d30780a6dba2a0b4888084e8b5e5c8590d4`。'
        '内置与此前实测一致的UNISOC VCOM 4.20.42.134，CAT和INF/SYS/DLL签名全过；'
        '写入/恢复前自动检查，缺少则经Windows UAC预装，已安装跳过，失败或要求重启时停止。'
        '10项新HOST检查、修正OEM INF路径后的本机只读识别、中文空格路径/隔离运行时和ZIP全成员验证通过。'
        'system载荷未改，复用v1已过证据。**仍待干净PC驱动首装和system实机写入/启动/功能/恢复，'
        '本轮没有驱动安装或设备操作。** 根入口已接v2，增加单独驱动入口；详见 '
        '`04_Documents/P011-Bili免ADB含驱动刷写包-20261014.md`。以下无驱动/未生成等为历史阶段。\n\n'
    )
    documents = [ROOT / '01_Environment/00-项目交接与当前状态.md', ROOT / '01_Environment/02-工具版本与验证边界.md',
        HERE.parents[1] / 'NO_ADB_DISTRIBUTION.md', HERE.parents[1] / 'NO_ADB_NEXT_GATE.md', HERE.parent / 'README.md',
        ROOT / '04_Documents/P011-Bili免ADB刷写包制作-20261014.md']
    for path in documents:
        source = path.read_text(encoding='utf-8-sig')
        assert '含驱动免ADB包已制作（2026-10-14）' not in source
        heading, rest = source.split('\n', 1)
        path.write_text(heading + '\n\n' + status + rest.lstrip('\n'), encoding='utf-8')
    unit = {'scope': 'HOST_ONLY_NO_UAC_NO_INSTALL_NO_USB', 'test_count': 10, 'passed': 10,
        'record_kind': 'derived_from_tool_result_not_an_independent_raw_stream', 'tool_chunk': 'e0a679',
        'host_exit': 0, 'unittest_elapsed_seconds': 0.025,
        'source_at_test': 'driver-integration/test_driver.py',
        'note': 'Initial 10 tests passed before OEM-name compatibility fix; final native readonly check covers that fix.'}
    (HERE / 'driver-host-tests-result.json').write_text(json.dumps(unit, ensure_ascii=False, indent=2), encoding='utf-8')
    files = {REPORT, HERE / 'driver-package-result.json', HERE / 'driver-host-tests-result.json',
        HERE / 'prepare_driver.py', HERE / 'build_driver_package.py', HERE / 'finalize_driver_package.py', pathlib.Path(__file__)}
    for folder in ('driver-integration', 'driver-input-20261014', 'root-entry-before-driver'):
        files.update(p for p in (HERE / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    for folder in ('driver-host-validation-20261014', 'driver-host-validation-20261014-corrected'):
        directory = HERE / folder
        files.update(p for p in directory.iterdir() if p.is_file())
        files.update(p for p in (directory / 'readonly-existing-driver').rglob('*') if p.is_file())
    files.update([HERE / 'out/P011-Bili-NoADB-v2-driver-20261014/app/driver_setup.py',
        HERE / 'out/P011-Bili-NoADB-v2-driver-20261014/package-manifest.json',
        HERE / 'out/P011-Bili-NoADB-v2-driver-final-20261014/package-manifest.json'])
    files.update(ROOT / name for name in RESULT['root_entries_updated'])
    files.update(documents)
    manifest = {path.relative_to(ROOT).as_posix(): {'bytes': path.stat().st_size, 'sha256': sha(path)} for path in sorted(files)}
    archive = ROOT / 'packages/P011-Bili-NoADB-driver-evidence-20261014.zip'
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(files):
            bundle.write(path, path.relative_to(ROOT).as_posix())
        bundle.writestr('audit-manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        for name, row in manifest.items():
            value = bundle.read(name)
            assert len(value) == row['bytes'] and hashlib.sha256(value).hexdigest() == row['sha256']
    result = {'evidence': str(archive), 'bytes': archive.stat().st_size, 'sha256': sha(archive),
        'members': len(manifest) + 1, 'all_member_sha_crc_passed': True, 'device_operations': False}
    (HERE / 'driver-delivery-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
