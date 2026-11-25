"""One targeted follow-up after rc5/SysV were identified; no device I/O."""
import hashlib
import json
import pathlib
import subprocess

IMAGE = pathlib.Path('/src/06_Firmware/backups/v2.4.0-20260923-162730/p29-system.img')
OUT = pathlib.Path('/out/evidence/startup-followup')
READS = ('stat /etc/rc0.d', 'stat /etc/rc6.d', 'stat /etc/rcS.d/S04mountall.sh',
         'stat /etc/rc5.d/S09weston', 'stat /etc/rc5.d/S90control_engine-init',
         'stat /etc/rc5.d/S96zybz03qt-init')
FILES = ('/etc/init.d/mountall.sh', '/etc/default/rcS', '/sbin/init.sysvinit',
         '/etc/init.d/partion-mount')

def main():
    OUT.mkdir(parents=True, exist_ok=False)
    commands = list(READS)
    commands.extend('dump ' + source + ' ' + str(OUT / source.lstrip('/').replace('/', '__')) for source in FILES)
    rows = []
    for index, command in enumerate(commands):
        proc = subprocess.run(['debugfs', '-R', command, str(IMAGE)], capture_output=True)
        (OUT / ('%02d.stdout.raw' % index)).write_bytes(proc.stdout)
        (OUT / ('%02d.stderr.raw' % index)).write_bytes(proc.stderr)
        rows.append(dict(command=command, host_exit=proc.returncode))
    files = []
    for source in FILES:
        path = OUT / source.lstrip('/').replace('/', '__')
        if path.is_file():
            raw = path.read_bytes()
            files.append(dict(source=source, file=path.name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
    (OUT / 'manifest.json').write_text(json.dumps(dict(scope='HOST_ONLY_TARGETED_READ_NO_IMAGE_WRITE',
        commands=rows, files=files), indent=2), encoding='utf-8')
    print(json.dumps(dict(commands=len(rows), files=files), indent=2))

if __name__ == '__main__':
    main()
