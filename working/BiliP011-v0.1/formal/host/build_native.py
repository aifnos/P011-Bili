"""Build isolated formal native runtime; no ADB, downloads, or legacy output writes."""
import datetime
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parents[2]
FORMAL = BASE / 'formal'
NATIVE = FORMAL / 'native'
MEDIA = BASE / 'out/media-6d99b414a032ec70'
IMAGE = 'p011-bili-builder:abi227'
VOLUME = 'p011-bili-build-20260923'
CHANGES = {'client/player_v2.cpp': ('seconds>480', 'seconds>86400'),
           'client/hardware_worker.cpp': ('limit>480', 'limit>86400')}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pinned_media():
    raw = (MEDIA / 'manifest.json').read_bytes()
    if MEDIA.name != 'media-' + sha(raw)[:16]:
        raise ValueError('Base media identity differs')
    manifest = json.loads(raw)
    for name, spec in manifest.items():
        path = MEDIA / name
        if path.is_symlink() or path.resolve().parent == MEDIA.parent:
            raise ValueError('Invalid base media member: ' + name)
        body = path.read_bytes()
        if sha(body) != spec['sha256'] or len(body) != spec['bytes']:
            raise ValueError('Base media bytes differ: ' + name)
    return raw, manifest


def prepare_sources():
    paths = sorted((BASE / 'client').glob('*.cpp')) + sorted((BASE / 'client').glob('*.hpp'))
    paths += [BASE / 'probes/memion_cache.cpp', BASE / 'probes/omx_cache_bridge.h']
    files, original, diff = {}, {}, []
    for source in paths:
        name = source.relative_to(BASE).as_posix()
        before = source.read_bytes()
        after = before
        if name in CHANGES:
            old, new = CHANGES[name]
            if before.count(old.encode()) != 1:
                raise ValueError('Original bound identity differs: ' + name)
            after = before.replace(old.encode(), new.encode(), 1)
            diff.extend(difflib.unified_diff(before.decode().splitlines(True), after.decode().splitlines(True), fromfile='original/' + name, tofile='formal/native/' + name))
        target = NATIVE / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.is_symlink() or target.read_bytes() != after:
                raise ValueError('Formal source differs; refusing overwrite: ' + name)
        else:
            target.write_bytes(after)
        files['formal/native/' + name] = sha(after)
        original[name] = sha(before)
    # Every source outside the two explicit upper bounds remains byte-identical.
    for name, change in CHANGES.items():
        body = (NATIVE / name).read_bytes()
        if body.replace(change[1].encode(), change[0].encode(), 1) != (BASE / name).read_bytes():
            raise ValueError('Unexpected source change: ' + name)
    return files, original, ''.join(diff)


def main():
    base_raw, base_manifest = pinned_media()
    sys.path.insert(0, str(BASE / 'host'))
    from strip_player_artifact import validate_strip_player
    validate_strip_player(BASE)
    sources, original, diff = prepare_sources()
    for path in (NATIVE / 'build_container.py', Path(__file__)):
        sources[path.relative_to(BASE).as_posix()] = sha(path.read_bytes())
    image = json.loads(subprocess.check_output(['docker', 'image', 'inspect', IMAGE], text=True))[0]
    identity = sha(json.dumps(dict(source_files=sources, base_media_sha256=sha(base_raw),
                                 image_id=image['Id'], playback_limit_seconds=86400), sort_keys=True).encode())
    output = FORMAL / 'out' / ('native-' + identity[:16])
    if output.exists():
        result = json.loads((output / 'build-result.json').read_text(encoding='utf-8'))
        if result.get('status') != 'HOST_ONLY' or result.get('source_files') != sources:
            raise ValueError('Existing incomplete or mismatched immutable build; refusing overwrite')
        for name, spec in result['artifacts'].items():
            path = output / name
            if path.is_symlink() or sha(path.read_bytes()) != spec['sha256']:
                raise ValueError('Existing native artifact changed')
        print('FORMAL_NATIVE=' + str(output), flush=True)
        print('STATUS=HOST_ONLY (existing verified build)', flush=True)
        return
    output.mkdir(parents=True)
    (output / 'source.diff').write_text(diff, encoding='utf-8', newline='')
    command = ['docker', 'run', '--rm', '--network', 'none',
               '--mount', 'type=bind,source=' + str(BASE) + ',target=/src,readonly',
               '--mount', 'type=volume,source=' + VOLUME + ',target=/work,readonly',
               '--mount', 'type=bind,source=' + str(output) + ',target=/output',
               image['Id'], 'python3', '-B', '/src/formal/native/build_container.py']
    (output / 'command.json').write_text(json.dumps(command, indent=2), encoding='utf-8')
    (output / 'source-manifest.json').write_text(json.dumps(dict(source_files=sources,
        original_source_files=original, allowed_changes=CHANGES), indent=2), encoding='utf-8')
    print('FORMAL_NATIVE=' + str(output), flush=True)
    with (output / 'build.stdout.raw').open('xb') as stdout, (output / 'build.stderr.raw').open('xb') as stderr:
        exit_code = subprocess.call(command, cwd=BASE, stdout=stdout, stderr=stderr)
    result = dict(schema=1, formal_runtime=exit_code == 0, playback_limit_seconds=86400,
                  status='HOST_ONLY' if exit_code == 0 else 'BUILD_FAILED', device_tested=False,
                  host_exit=exit_code, command=command, source_files=sources,
                  original_source_files=original, allowed_changes=CHANGES,
                  base_media=MEDIA.name, base_media_manifest_sha256=sha(base_raw),
                  docker_image_id=image['Id'], docker_volume=VOLUME,
                  started_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  observations='Host cross-build and static source/ELF checks only; no P011 hardware playback test.')
    if exit_code == 0:
        result.update(json.loads((output / 'container-result.json').read_text(encoding='utf-8')))
        # Match the old pair's dynamic dependencies; the fixed media supplies the same SDL/OMX.
        for name, spec in result['artifacts'].items():
            if spec['needed'] != base_manifest[name]['needed']:
                raise ValueError('Formal dynamic dependencies differ: ' + name)
        if sources != {name: sha((BASE / name).read_bytes()) for name in sources}:
            raise ValueError('Formal sources changed during build')
        pinned_media()
    (output / 'build-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('STATUS=' + result['status'], flush=True)
    if exit_code:
        print((output / 'build.stderr.raw').read_text(encoding='utf-8', errors='replace')[-6000:])
    raise SystemExit(exit_code)


if __name__ == '__main__':
    main()
