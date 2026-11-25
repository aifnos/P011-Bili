"""PC-only targeted debugfs reads; never mount or modify the original image."""
import hashlib
import json
import pathlib
import subprocess


IMAGE = pathlib.Path('/src/06_Firmware/backups/v2.4.0-20260923-162730/p29-system.img')
OUT = pathlib.Path('/out/evidence/startup-targeted')
FILES = ('/etc/inittab', '/etc/init.d/rcS', '/etc/init.d/rc', '/etc/fstab')
READS = ('stat /sbin/init', 'stat /linuxrc', 'stat /bin/busybox', 'ls -l /etc/init.d',
         'ls -l /etc/rcS.d', 'ls -l /etc/rc5.d')


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    if IMAGE.stat().st_size != 1073741824:
        raise ValueError('Pinned system image length differs')
    commands = list(READS)
    for source in FILES:
        commands.append('dump ' + source + ' ' + str(OUT / source.lstrip('/').replace('/', '__')))
    rows = []
    for index, command in enumerate(commands):
        proc = subprocess.run(['debugfs', '-R', command, str(IMAGE)], capture_output=True)
        prefix = OUT / ('%02d' % index)
        prefix.with_suffix('.stdout.raw').write_bytes(proc.stdout)
        prefix.with_suffix('.stderr.raw').write_bytes(proc.stderr)
        rows.append(dict(command=command, host_exit=proc.returncode,
                         stdout_sha256=hashlib.sha256(proc.stdout).hexdigest(),
                         stderr_sha256=hashlib.sha256(proc.stderr).hexdigest()))
    files = []
    for source in FILES:
        path = OUT / source.lstrip('/').replace('/', '__')
        if path.is_file():
            raw = path.read_bytes()
            files.append(dict(source=source, file=path.name, bytes=len(raw),
                              sha256=hashlib.sha256(raw).hexdigest()))
    result = dict(scope='HOST_ONLY_DEBUGFS_READ_NO_MOUNT', image=str(IMAGE),
                  image_bytes=IMAGE.stat().st_size, image_hash_not_repeated=True,
                  reference_image_sha256='6bf4706e5f03ed79edfe0e4ab337dbcc1310d6a7b57116a09ecfa756b4de648f',
                  adb_invoked=False, usb_accessed=False, target_executed=False,
                  original_image_modified=False, commands=rows, files=files)
    (OUT / 'manifest.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
