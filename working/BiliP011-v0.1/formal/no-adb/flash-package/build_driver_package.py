"""Create immutable driver-inclusive v2 from the verified v1, no hardware IO."""
import hashlib
import json
import pathlib
import shutil
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
OLD = HERE / 'out/P011-Bili-NoADB-v1-final-20261014'
NAME = 'P011-Bili-NoADB-v2-driver-final-20261014'
OUT = HERE / 'out' / NAME
INPUT = HERE / 'driver-input-20261014'
SOURCE = HERE / 'driver-integration'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    old_manifest = json.loads((OLD / 'package-manifest.json').read_bytes())
    for name, row in old_manifest['files'].items():
        assert sha(OLD / name) == row['sha256'] and (OLD / name).stat().st_size == row['bytes']
    signatures = json.loads((INPUT / 'signature-results.json').read_text(encoding='utf-8-sig'))
    assert len(signatures) == 4 and all(row['exit'] == 0 for row in signatures)
    shutil.copytree(OLD, OUT)
    for name in ('driver_setup.py', 'run.py'):
        shutil.copyfile(SOURCE / name, OUT / 'app' / name)
    shutil.copytree(INPUT / 'signed-driver', OUT / 'drivers/UNISOC-VCOM-4.20.42.134')
    shutil.copyfile(INPUT / 'driver-source.json', OUT / 'drivers/driver-source.json')
    shutil.copyfile(SOURCE / 'DRIVER-NOTICES.md', OUT / 'drivers/驱动来源与说明.md')
    shutil.copyfile(SOURCE / 'DRIVER-NOTICES.md', OUT / 'licenses/Driver-notices.md')
    shutil.copyfile(INPUT / 'signature-results.json', OUT / 'evidence/driver-signature-results.json')
    for path in INPUT.glob('*.raw'):
        shutil.copyfile(path, OUT / 'evidence' / ('driver-' + path.name))
    python_notice = OUT / 'licenses/Python-notices.md'
    original_notice = python_notice.read_text(encoding='utf-8')
    python_notice.write_text('> 本文件保留先前 Python 运行时阶段的原始来源与状态记录。本版已另行内置下载串口驱动，当前情况见 `Driver-notices.md`。\n\n' + original_notice, encoding='utf-8')
    readme = (OLD / '使用说明.md').read_text(encoding='utf-8')
    readme = readme.replace('# P011 B站下载模式刷写包', '# P011 B站下载模式刷写包（含驱动）')
    old_line = '2. 电脑须已有设备厂商提供的签名 SPRD 下载驱动。缺少驱动时程序停止；本包不捆绑未核实来源的驱动，也不修改驱动签名设置。'
    new_line = '2. 已内置 Microsoft 签名的 UNISOC 下载串口驱动。写入和恢复入口会先检查：匹配驱动已注册则跳过；缺少时自动请求 Windows 管理员授权并预装。请允许 UAC 提示，完成后按程序提示插入设备。取消授权、安装失败或要求重启时，本次停止。也可单独运行 **一键安装下载驱动.cmd**。不需要自行下载驱动或关闭签名验证。'
    assert old_line in readme
    readme = readme.replace(old_line, new_line).replace('支持 Windows x64', '支持 Windows 10/11 x64（不支持 ARM64）')
    readme = readme.replace('- `校验刷写包.cmd`：仅核对电脑文件，不枚举或连接设备。', '- `校验刷写包.cmd`：仅核对电脑文件，不枚举或连接设备。\n- `一键安装下载驱动.cmd`：只检查或预装内置驱动，不启动刷写。\n- `drivers`：签名 VCOM 驱动、固定来源与安装说明。')
    readme += '\n驱动版本 `4.20.42.134`，硬件 ID `1782:4D00`，与此前本机下载模式实测所用文件一致。完整 CAT 签名和 INF/SYS/DLL 目录成员验证通过；来源与原版权见 `drivers/驱动来源与说明.md`。仅预装该串口驱动，不安装 ADB 驱动。预装成功不等于设备已绑定成功；首次插入仍须 Windows 完成正常枚举，包本身的干净电脑首装与 system 实机验收仍待。\n'
    (OUT / '使用说明.md').write_text(readme, encoding='utf-8')
    entry = (OLD / '一键正式写入B站.cmd').read_bytes().replace(b'run.py" install', b'run.py" driver')
    assert b'run.py" driver' in entry
    (OUT / '一键安装下载驱动.cmd').write_bytes(entry)
    # Original source records, including unmodified downloaded INF and license.
    with zipfile.ZipFile(OUT / 'source/driver-source-record.zip', 'x', zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted((INPUT / 'upstream').rglob('*')):
            if path.is_file():
                bundle.write(path, path.relative_to(INPUT).as_posix())
        for name in ('driver-source.json', 'upstream-tree.json', 'signature-results.json'):
            bundle.write(INPUT / name, name)
        for path in sorted(INPUT.glob('*.raw')):
            bundle.write(path, 'signature-check/' + path.name)
        bundle.write(SOURCE / 'DRIVER-NOTICES.md', 'DRIVER-NOTICES.md')
    with zipfile.ZipFile(OLD / 'source/project-sources.zip') as prior, zipfile.ZipFile(OUT / 'source/project-sources.zip', 'w', zipfile.ZIP_DEFLATED) as current:
        for item in prior.infolist():
            name = 'installer/history/no-driver-run.py' if item.filename == 'installer/run.py' else item.filename
            current.writestr(name, prior.read(item))
        for name in ('run.py', 'driver_setup.py', 'test_driver.py'):
            current.write(SOURCE / name, 'installer/' + name)
        current.write(pathlib.Path(__file__), 'installer/build_driver_package.py')
        current.write(HERE / 'prepare_driver.py', 'installer/prepare_driver.py')
    files = {p.relative_to(OUT).as_posix(): {'bytes': p.stat().st_size, 'sha256': sha(p)}
        for p in sorted(OUT.rglob('*')) if p.is_file() and p.name != 'package-manifest.json'}
    manifest = dict(old_manifest, name=NAME, driver_included=True,
        driver_version='4.20.42.134', driver_signature_verified=True,
        driver_hardware_id='USB\\VID_1782&PID_4D00', driver_auto_prepare=True,
        driver_clean_pc_install_tested=False, files=files)
    (OUT / 'package-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'package': str(OUT), 'files': len(files) + 1,
        'candidate_sha256_unchanged': manifest['candidate_sha256'], 'driver_included': True}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
