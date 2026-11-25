"""Fetch pinned signed VCOM dependency, never install it."""
import concurrent.futures
import hashlib
import json
import pathlib
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / 'driver-input-20261014'
COMMIT = 'afdaf779a1981c8fedd21cb7198b4b706713f045'
PREFIX = 'file/drive/SPD_Driver/Drivers/DriversForWin10/Drivers/'
RAW = 'https://raw.githubusercontent.com/ColdWindScholar/CWHelper/' + COMMIT + '/'
FILES = ['sprdvcom.inf', 'sprdvcom.cat', 'amd64/sprdvcom.sys', 'amd64/WdfCoInstaller01009.dll']


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    tree = {row['path']: row for row in json.loads((OUT / 'upstream-tree.json').read_text(encoding='utf-8-sig'))['tree']}
    sources = [PREFIX + name for name in FILES] + ['LICENSE', 'readme.md']
    def fetch(name):
        req = urllib.request.Request(RAW + name, headers={'User-Agent': 'P011-package-audit'})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read(4 * 1024 * 1024)
        assert len(data) == tree[name]['size']
        assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == tree[name]['sha']
        relative = name.removeprefix(PREFIX) if name.startswith(PREFIX) else 'repository-' + name
        original = OUT / 'upstream' / relative
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(data)
        return name, relative, data
    result = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for source, relative, data in pool.map(fetch, sources):
            row = {'source': RAW + source, 'git_blob_sha1': tree[source]['sha'], 'upstream_bytes': len(data), 'upstream_sha256': sha(data)}
            if source.startswith(PREFIX):
                original = data
                if relative == 'sprdvcom.inf':
                    assert sha(data) == '9f97d53076be4b280489605f0282c8b94235a0bfab84126f825eab01a087c88b'
                    data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
                    assert sha(data) == '7aa924930285803b50f4468f071657da11c4764b4364d4cca43757e766cd6987'
                target = OUT / 'signed-driver' / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                local = pathlib.Path('C:/Windows/System32/DriverStore/FileRepository/sprdvcom.inf_amd64_4036a4c9348baf8a') / relative
                assert local.read_bytes() == data
                row.update({'name': relative, 'bytes': len(data), 'sha256': sha(data), 'only_crlf_restored': data != original, 'same_as_previously_used_local_driver': True})
            result.append(row)
    manifest = {'version': '4.20.42.134', 'date': '2020-10-14', 'hardware_id': 'USB\\VID_1782&PID_4D00',
        'source_commit': COMMIT, 'source_kind': 'pinned_public_mirror_not_manufacturer_download',
        'driverstore_exported': False, 'files': result, 'installed_by_this_run': False,
        'repository_license_is_not_asserted_as_driver_license': True}
    (OUT / 'driver-source.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
