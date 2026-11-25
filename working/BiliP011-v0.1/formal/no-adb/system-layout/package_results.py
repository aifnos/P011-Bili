"""Archive this new private HOST candidate and verify archive member bytes."""
import datetime
import hashlib
import json
import pathlib
import zipfile

HERE = pathlib.Path(__file__).resolve().parent


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    results = HERE / 'results'
    results.mkdir(exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y%m%d-%H%M%S')
    archive = results / ('P011-Bili-SystemLayout-7d8e33be09953969b7670025-' + stamp + '.private.zip')
    files = sorted(path for path in HERE.rglob('*') if path.is_file() and
                   'results' not in path.relative_to(HERE).parts and '__pycache__' not in path.parts)
    rows = {}
    for path in files:
        raw = path.read_bytes()
        rows[str(path.relative_to(HERE)).replace('\\', '/')] = dict(bytes=len(raw), sha256=digest(raw))
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as output:
        for path in files:
            output.write(path, str(path.relative_to(HERE)).replace('\\', '/'))
        output.writestr('archive-members.json', json.dumps(rows, indent=2))
    with zipfile.ZipFile(archive) as check:
        if check.testzip() is not None:
            raise ValueError('Archive CRC verification failed')
        for name, expected in rows.items():
            raw = check.read(name)
            if len(raw) != expected['bytes'] or digest(raw) != expected['sha256']:
                raise ValueError('Archive member readback differs: ' + name)
    report = dict(scope='HOST_PRIVATE_LAYOUT_CANDIDATE_NO_IMAGE_NO_DEVICE', archive=str(archive),
                  archive_bytes=archive.stat().st_size, sha256=digest(archive.read_bytes()),
                  member_count=len(rows) + 1, crc_verified=True, every_member_sha256_verified=True,
                  old_formal_tests_repeated=False, adb_invoked=False, usb_accessed=False,
                  original_image_modified=False, image_built=False)
    (results / (archive.name + '.verification.json')).write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
