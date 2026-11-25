"""Build portable, source-inclusive no-ADB package from verified local inputs."""
import hashlib
import json
import pathlib
import shutil
import struct
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
NO_ADB = HERE.parent
FORMAL = NO_ADB.parent
BILI = FORMAL.parent
PROJECT = BILI.parents[1]
NAME = 'P011-Bili-NoADB-v1-final-20261014'
OUT = HERE / 'out' / NAME
IMAGE = HERE / 'image-build-20261014-v3/system-bili.img'
BASE = PROJECT / '06_Firmware/backups/v2.4.0-20260923-162730/p29-system.img'
LAYOUT = NO_ADB / 'system-layout/out/7d8e33be09953969b7670025'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for part in iter(lambda: source.read(1048576), b''):
            h.update(part)
    return h.hexdigest()


def copy(source, name):
    target = OUT / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def patch(source, target, destination):
    count = 0
    with source.open('rb') as old, target.open('rb') as new, destination.open('xb') as out:
        out.write(b'P011DIF1' + bytes(4))
        pending = bytearray()
        start = offset = 0
        while True:
            before, after = old.read(4096), new.read(4096)
            if before == b'' and after == b'':
                break
            assert len(before) == len(after) == 4096
            if before != after:
                if not pending:
                    start = offset
                pending.extend(after)
            if pending and (before == after or len(pending) == 1048576):
                out.write(struct.pack('<QI', start, len(pending)) + pending)
                count += 1
                pending.clear()
            offset += 4096
        if pending:
            out.write(struct.pack('<QI', start, len(pending)) + pending)
            count += 1
        out.seek(8)
        out.write(struct.pack('<I', count))
    return count


def main():
    result = json.loads((IMAGE.parent / 'image-result.json').read_bytes())
    assert result['status'] == 'HOST_FULL_SYSTEM_IMAGE_VERIFIED_DEVICE_PENDING'
    assert sha(IMAGE) == result['candidate_sha256'] and sha(BASE) == result['base_sha256']
    OUT.mkdir(parents=True, exist_ok=False)
    (OUT / 'data').mkdir()
    count = patch(BASE, IMAGE, OUT / 'data/system.delta')
    copy(PROJECT / '06_Firmware/metadata/pgpt.bin', 'data/reference-gpt.bin')
    for source in (HERE / 'app').glob('*.py'):
        copy(source, 'app/' + source.name)
    for name in ('storage_read_codec.py', 'win32_download_transport.py', 'gpt_readback.py', 'run_early_mode_probe.py'):
        copy(NO_ADB / name, 'app/' + name)
    runtime = NO_ADB / 'portable-runtime/python-3.14.8-embed-amd64'
    runtime_manifest = json.loads((NO_ADB / 'portable-runtime/manifest.json').read_bytes())
    for row in runtime_manifest['upstream_members']:
        name = row['name']
        if name == 'python314._pth':
            continue
        source = runtime / name
        assert sha(source) == row['sha256']
        copy(source, 'runtime/' + name)
    (OUT / 'runtime/python314._pth').write_text('python314.zip\n.\n..\\app\n', encoding='ascii')
    copy(NO_ADB / 'portable-runtime/THIRD_PARTY_NOTICES.md', 'licenses/Python-notices.md')
    copy(NO_ADB / 'portable-runtime/sources/python-3.14.8-embed-amd64.zip.spdx.json', 'licenses/python-sbom.json')
    payload = LAYOUT / 'system-files/opt/p011-bili/releases/7d8e33be09953969b7670025/app'
    for name in ('THIRD_PARTY_NOTICES.md', 'GPL-3.0.txt', 'PINYIN-LICENSE.txt', 'PINYIN-AUTHORS.txt'):
        copy(payload / name, 'licenses/' + name)
    # Corresponding project sources and local modified dependencies, no user data.
    source_zip = OUT / 'source/project-sources.zip'
    source_zip.parent.mkdir()
    allowed = {'.py', '.cpp', '.c', '.h', '.hpp', '.qml', '.js', '.md', '.txt', '.json', '.in', '.cmake', '.sh'}
    source_roots = [(FORMAL / 'out/P011-Bili-Formal-v1-final-20261014/source', 'formal'),
                    (BILI / 'build', 'build'), (BILI / 'third_party/SDL2-2.0.8-p011', 'third_party/SDL2-2.0.8-p011'),
                    (BILI / 'third_party/gst-omx-1.14.2-p011', 'third_party/gst-omx-1.14.2-p011'),
                    (LAYOUT / 'system-files', 'installed-source')]
    with zipfile.ZipFile(source_zip, 'x', zipfile.ZIP_DEFLATED) as archive:
        for folder, prefix in source_roots:
            for path in sorted(folder.rglob('*')):
                if (not path.is_file() or path.is_symlink() or '__pycache__' in path.parts or
                        path.suffix.lower() not in allowed):
                    continue
                archive.write(path, prefix + '/' + path.relative_to(folder).as_posix())
        for path in (HERE / 'app').glob('*.py'):
            archive.write(path, 'installer/' + path.name)
        archive.write(pathlib.Path(__file__), 'installer/build_package.py')
        archive.write(HERE / 'build_image.py', 'installer/build_image.py')
    copy(BILI / 'out/dependency-sources-ae80b9c92d1d16ee.zip', 'source/dependency-sources.zip')
    copy(IMAGE.parent / 'image-result.json', 'evidence/image-result.json')
    for name in ('candidate-fsck.stdout.raw', 'candidate-fsck.stderr.raw', 'candidate-fsck.exit.txt'):
        copy(IMAGE.parent / name, 'evidence/' + name)
    for filename, mode in [('一键正式写入B站.cmd', 'install'), ('一键恢复原系统.cmd', 'restore'), ('校验刷写包.cmd', 'check')]:
        body = '@echo off\r\nchcp 65001 >nul\r\n"%~dp0runtime\\python.exe" -B -X utf8 -u "%~dp0app\\run.py" ' + mode + '\r\nset "P011_RESULT=%ERRORLEVEL%"\r\necho.\r\necho 退出码: %P011_RESULT%\r\npause\r\nexit /b %P011_RESULT%\r\n'
        (OUT / filename).write_bytes(body.encode('utf-8'))
    copy(HERE / 'README-user.md', '使用说明.md')
    files = {p.relative_to(OUT).as_posix(): dict(bytes=p.stat().st_size, sha256=sha(p))
             for p in sorted(OUT.rglob('*')) if p.is_file()}
    manifest = dict(schema='p011.no-adb.package.v1', name=NAME,
        status='HOST_BUILT_SYSTEM_DEVICE_ACCEPTANCE_PENDING', firmware='z031_v2.4.0-20251128_174826-user',
        base_sha256=result['base_sha256'], candidate_sha256=result['candidate_sha256'], system_bytes=result['bytes'],
        release_id=result['release_id'], patch_records=count, driver_included=False, python_included=True,
        adb_required=False, donor_userdata_included=False, donor_nv_included=False,
        full_original_firmware_included=False, settings_label='用户反馈', files=files)
    (OUT / 'package-manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(dict(output=str(OUT), files=len(files), patch_bytes=(OUT/'data/system.delta').stat().st_size,
        patch_records=count, candidate_sha256=result['candidate_sha256']), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
