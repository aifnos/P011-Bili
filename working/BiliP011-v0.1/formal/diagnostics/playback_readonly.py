"""Read existing installed playback evidence through the legacy ADB reader."""
import ast
import datetime
import importlib.util
import json
import pathlib
import re
import subprocess
import zipfile

FORMAL = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = FORMAL / 'out/P011-Bili-Formal-v5-adb-directory-20261014'
spec = importlib.util.spec_from_file_location('legacy_reader', PACKAGE / 'install_formal.py')
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)
stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
out = FORMAL / 'evidence' / ('playback-readonly-' + stamp)
out.mkdir()
adb = reader.Adb(out)
devices = adb.run('devices', ['devices', '-l'])
targets = re.findall(r'^\S+\s+device\s+.*model:sprdisk .*transport_id:(\d+)', devices, re.M)
if len(targets) != 1:
    raise RuntimeError('Exactly one connected P011 required')
adb.transport = int(targets[0])
code = r'''
import os, sys, stat, hashlib, subprocess
rid = '9412e49de8feb2d6b2677180'
release = '/mnt/data/p011-toolbox/bili-formal/releases/' + rid
root = '/mnt/data/p011-toolbox/bili-awake/' + rid
sys.path.insert(0, release + '/app')
import p011_json as json
def read(path, limit=32768):
    with open(path, 'rb') as f:
        return f.read(limit)
assert os.getuid() == 0
report = dict(uid=os.getuid(), uname=list(os.uname()), release=rid,
              files={}, processes=[], runtime_names=[])
for path in ('/etc/version', '/etc/os-release', '/proc/sys/kernel/random/boot_id'):
    if os.path.isfile(path):
        report['files'][path] = read(path).decode('utf8', 'replace')
for name in ('play-diagnostic.json', 'player-result.json', 'hardware-result.json',
             'hw-result.json', 'prefetch-result.json', 'hardware-error.json',
             'hardware-lifecycle.json', 'player-startup.json', 'phase-result.json'):
    path = root + '/' + name
    if os.path.isfile(path) and not os.path.islink(path):
        report['files'][name] = read(path).decode('utf8', 'replace')
if os.path.isdir(root):
    report['runtime_names'] = sorted(os.listdir(root))[:100]
for name in os.listdir('/proc'):
    if not name.isdigit(): continue
    base = '/proc/' + name
    try:
        exe = os.readlink(base + '/exe')
        args = read(base + '/cmdline').split(b'\0')
        if not (exe in ('/usr/bin/Z03', '/usr/bin/control_engine', '/usr/bin/weston')
                or any(release.encode() in a for a in args)):
            continue
        fields = read(base + '/stat').decode().rsplit(')', 1)[1].split()
        env = {}
        for entry in read(base + '/environ').split(b'\0'):
            key, sep, value = entry.partition(b'=')
            if key.decode('ascii', 'ignore') in ('HOME', 'LD_LIBRARY_PATH', 'QT_QPA_PLATFORM',
                    'QT_PLUGIN_PATH', 'QML2_IMPORT_PATH', 'XDG_RUNTIME_DIR', 'WAYLAND_DISPLAY',
                    'GST_PLUGIN_PATH', 'GST_OMX_CONFIG_DIR', 'PULSE_SERVER'):
                env[key.decode()] = value.decode('utf8', 'replace')
        row = dict(pid=int(name), ppid=int(fields[1]), start=fields[19], exe=exe, env=env,
                   args=[a.decode('utf8','replace') for a in args[:4]],
                   cwd=os.readlink(base + '/cwd'))
        report['processes'].append(row)
    except (OSError, ValueError): pass
for path in (release+'/media/bin/bili-player', release+'/media/bin/bili-hw',
             release+'/app/formal_service.py', release+'/app/service.py', '/usr/bin/Z03'):
    if os.path.isfile(path):
        report['files'][path] = {'sha256':hashlib.sha256(read(path, 64*1024*1024)).hexdigest(),
                                 'mode':oct(os.stat(path).st_mode & 4095)}
child = subprocess.Popen(['/bin/dmesg'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
stdout, stderr = child.communicate()
report['kernel_media_tail'] = [line.decode('utf8','replace') for line in stdout.splitlines()
    if any(term in line.lower() for term in (b'segfault',b'bili-',b'out of memory',b'oom-kill'))][-25:]
report['dmesg_exit'] = child.returncode
report['dmesg_stderr_bytes'] = len(stderr)
print('RESULT=' + repr(report), flush=True)
'''
(out / 'remote-readonly.py').write_text(code, encoding='utf8')
answer = reader.result(adb.python('playback-evidence', code, timeout=30))
(out / 'result.json').write_text(json.dumps(answer, ensure_ascii=False, indent=2), encoding='utf8')
with zipfile.ZipFile(str(out) + '.private.zip', 'x', zipfile.ZIP_DEFLATED) as z:
    for path in out.iterdir():
        if path.is_file(): z.write(path, path.name)
print(json.dumps({'evidence':str(out), 'diagnostics':{k:v for k,v in answer['files'].items()
    if '/' not in k}, 'runtime_names':answer['runtime_names'],
    'processes':answer['processes'], 'kernel':answer['kernel_media_tail']}, ensure_ascii=False))
