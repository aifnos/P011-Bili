"""Build a versioned playback worker fix; no device operations."""
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
FORMAL = HERE.parent
BASE = FORMAL.parent
OLD = FORMAL / 'native'
NATIVE = HERE / 'native'
OUT = HERE / 'build-v2'
OLD_PATTERN = '/mnt/data/p011-toolbox/bili-media/[a-f0-9]{16}/bin/bili-hw'
NEW_PATTERN = ('(?:/mnt/data/p011-toolbox/bili-media/[a-f0-9]{16}'
               '|/mnt/data/p011-toolbox/bili-formal/releases/[a-f0-9]{24}/media'
               '|/opt/p011-bili/releases/[a-f0-9]{24}/media)/bin/bili-hw')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    assert not OUT.exists(), 'Preserve existing candidate'
    original = json.loads((FORMAL / 'out/native-b2d39034f3adc93b/build-result.json').read_text())
    for name, digest in original['source_files'].items():
        assert sha((BASE / name).read_bytes()) == digest, name
    NATIVE.mkdir(parents=True, exist_ok=True)
    for folder in ('client', 'probes'):
        if not (NATIVE / folder).exists():
            shutil.copytree(OLD / folder, NATIVE / folder)
    gate = NATIVE / 'client/hardware_cache_gate.hpp'
    before = (OLD/'client/hardware_cache_gate.hpp').read_text(encoding='utf8')
    assert before.count(OLD_PATTERN) == 1
    after = before.replace(OLD_PATTERN, NEW_PATTERN, 1)
    assert gate.read_text(encoding='utf8') in (before, after)
    gate.write_text(after, encoding='utf8')
    assert after.replace(NEW_PATTERN, OLD_PATTERN, 1) == before
    container = (OLD / 'build_container.py').read_text(encoding='utf8')
    assert container.count("NATIVE = BASE / 'formal/native'") == 1
    container = container.replace("NATIVE = BASE / 'formal/native'",
                                  "NATIVE = BASE / 'formal/playback-fix-v1/native'", 1)
    (NATIVE / 'build_container.py').write_text(container, encoding='utf8')
    OUT.mkdir()
    (OUT / 'source.diff').write_text(''.join(difflib.unified_diff(
        before.splitlines(True), after.splitlines(True),
        fromfile='original/hardware_cache_gate.hpp', tofile='fixed/hardware_cache_gate.hpp')), encoding='utf8')
    sources = {p.relative_to(BASE).as_posix():sha(p.read_bytes())
               for p in NATIVE.rglob('*') if p.is_file()}
    image = json.loads(subprocess.check_output(['docker','image','inspect','p011-bili-builder:abi227']))[0]['Id']
    common = ['docker','run','--rm','--network=none',
              '--mount','type=bind,source='+str(BASE)+',target=/src,readonly',
              '--mount','type=volume,source=p011-bili-build-20260923,target=/work,readonly',
              '--mount','type=bind,source='+str(OUT)+',target=/output', image]
    test_command = common + ['python3','-B','/src/formal/playback-fix-v1/test_gate.py']
    with (OUT/'gate.stdout.raw').open('xb') as stdout, (OUT/'gate.stderr.raw').open('xb') as stderr:
        tests = subprocess.call(test_command, stdout=stdout, stderr=stderr)
    assert tests == 0, 'Fixed gate host checks failed'
    command = common + ['python3','-B','/src/formal/playback-fix-v1/native/build_container.py']
    with (OUT/'build.stdout.raw').open('xb') as stdout, (OUT/'build.stderr.raw').open('xb') as stderr:
        rc = subprocess.call(command, stdout=stdout, stderr=stderr)
    report = dict(host_exit=rc, formal_runtime=rc==0, device_tested=False,
                  playback_limit_seconds=86400, status='HOST_ONLY' if rc==0 else 'BUILD_FAILED',
                  source_files=sources, image=image, original_worker_sha256=original['artifacts']['bin/bili-hw']['sha256'],
                  allowed_change='Accept exact legacy, formal-data and formal-system media bundle locations',
                  gate_host_exit=tests)
    if rc == 0:
        report.update(json.loads((OUT/'container-result.json').read_text()))
        assert report['artifacts']['bin/bili-hw']['needed'] == original['artifacts']['bin/bili-hw']['needed']
        assert report['artifacts']['bin/bili-player']['sha256'] == original['artifacts']['bin/bili-player']['sha256'], 'Unchanged player must remain exact'
    (OUT/'build-result.json').write_text(json.dumps(report,indent=2), encoding='utf8')
    print(json.dumps({'host_exit':rc,'gate_host_exit':tests,'output':str(OUT),
                      'artifacts':report.get('artifacts',{})}, ensure_ascii=False))
    raise SystemExit(rc)


if __name__ == '__main__': main()
