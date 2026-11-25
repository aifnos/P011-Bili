"""Capture only our child and enforce a host watchdog; no device commands here."""
import hashlib
import json
import pathlib
import subprocess
import sys
import time

p = pathlib.Path(__file__).resolve().parent
before = {n:hashlib.sha256((p/n).read_bytes()).hexdigest() for n in ('engine.py', 'probe_cold.py')}
with (p/'cold2.stdout.raw').open('xb') as stdout, (p/'cold2.stderr.raw').open('xb') as stderr:
    proc = subprocess.Popen([sys.executable,'-B','-u','-X','utf8',str(p/'probe_cold.py')],
        stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW)
    (p/'cold2.child.json').write_text(json.dumps(dict(pid=proc.pid,source_sha256=before)),encoding='utf-8')
    timed_out = False
    try:
        code = proc.wait(timeout=240)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        code = proc.wait(timeout=10)
after = {n:hashlib.sha256((p/n).read_bytes()).hexdigest() for n in before}
result = dict(exit_code=code, timeout=timed_out, sources_before=before,sources_after=after,source_unchanged=before==after)
(p/'cold2.host-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
raise SystemExit(code if not timed_out else 124)
