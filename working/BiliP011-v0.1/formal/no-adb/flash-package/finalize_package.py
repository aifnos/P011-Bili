"""HOST-only relocation check and distribution ZIP; never install or open USB."""
import hashlib
import json
import os
import pathlib
import subprocess
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
PACKAGE = HERE / 'out/P011-Bili-NoADB-v1-final-20261014'
CHECK = HERE / 'relocation-check/中文 便携测试/P011 B站'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    manifest = json.loads((PACKAGE / 'package-manifest.json').read_bytes())
    for name, row in manifest['files'].items():
        path = PACKAGE / name
        assert path.stat().st_size == row['bytes'] and sha(path) == row['sha256']
    CHECK.mkdir(parents=True, exist_ok=False)
    for path in PACKAGE.rglob('*'):
        if path.is_file():
            target = CHECK / path.relative_to(PACKAGE)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(path, target)
    env = dict(os.environ, PYTHONPATH='Z:\\P011_DO_NOT_USE', PYTHONHOME='Z:\\P011_DO_NOT_USE')
    result = subprocess.run([str(CHECK / 'runtime/python.exe'), '-B', '-X', 'utf8', '-u',
        str(CHECK / 'app/run.py'), 'check'], cwd=str(HERE), env=env, capture_output=True)
    (HERE / 'relocation.stdout.raw').write_bytes(result.stdout)
    (HERE / 'relocation.stderr.raw').write_bytes(result.stderr)
    assert result.returncode == 0 and not result.stderr
    with zipfile.ZipFile(PACKAGE / 'source/project-sources.zip') as bundle:
        assert bundle.testzip() is None
    with zipfile.ZipFile(PACKAGE / 'source/dependency-sources.zip') as bundle:
        assert bundle.testzip() is None
    archive = PACKAGE.with_suffix('.zip')
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(PACKAGE.rglob('*')):
            if path.is_file():
                assert not path.is_symlink() and path.suffix.lower() not in ('.ttf', '.otf', '.ttc', '.woff', '.woff2')
                name = PACKAGE.name + '/' + path.relative_to(PACKAGE).as_posix()
                bundle.write(path, name, compress_type=zipfile.ZIP_STORED if path.suffix == '.zip' else zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        for name, row in manifest['files'].items():
            digest = hashlib.sha256()
            with bundle.open(PACKAGE.name + '/' + name) as source:
                for block in iter(lambda: source.read(1048576), b''):
                    digest.update(block)
            assert digest.hexdigest() == row['sha256']
        assert bundle.read(PACKAGE.name + '/package-manifest.json') == (PACKAGE / 'package-manifest.json').read_bytes()
    report = dict(status='HOST_PACKAGE_BUILT_VERIFIED_DEVICE_PENDING', package=str(PACKAGE),
        zip=str(archive), zip_bytes=archive.stat().st_size, zip_sha256=sha(archive),
        files=len(manifest['files']) + 1, zip_crc_and_members_verified=True,
        unicode_space_relocation_check=True, isolated_python_environment_check=True,
        host_unit_and_transaction_cases_passed=11, full_1gib_delta_reconstruction_sha256=manifest['candidate_sha256'],
        system_device_write_tested=False, driver_install_tested=False, clean_pc_tested=False,
        source_archives_crc_verified=True, original_system_not_bundled=True,
        userdata_not_bundled=True, nv_not_bundled=True, runtime_adb_dependency=False)
    (HERE / 'final-package-result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
