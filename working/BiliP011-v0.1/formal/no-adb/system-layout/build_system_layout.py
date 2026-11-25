"""Build a private system-file overlay candidate, never a flashable image.

All writes stay below this new directory. The original system image and old
formal package are inputs only. No target/ARM code or transport is executed.
"""
import ast
import hashlib
import importlib.util
import json
import pathlib
import re
import struct
import zlib

HERE = pathlib.Path(__file__).resolve().parent
FORMAL = HERE.parents[1]
PROJECT = HERE.parents[4]
PACKAGE = FORMAL / 'out/P011-Bili-Formal-v1-final-20261014'
OLD_ID = '9412e49de8feb2d6b2677180'
PINNED_MANIFEST = '23ad0c59124013311a50d7e2013fc6e62839fcf797cb11826a3dbd2658e25321'
IMAGE_SHA = '6bf4706e5f03ed79edfe0e4ab337dbcc1310d6a7b57116a09ecfa756b4de648f'
SOURCE_NAMES = ('build_system_layout.py', 'system_bootstrap.py.in', 'init-script.sh.in',
                'inspect_startup.py', 'inspect_startup_followup.py', 'test_system_layout.py')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def read_regular(path):
    require(path.is_file() and not path.is_symlink(), 'Missing/linked input: ' + str(path))
    return path.read_bytes()


def decoder():
    spec = importlib.util.spec_from_file_location('readonly_original_qrc_decoder', FORMAL / 'host/build_formal.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def startup_evidence():
    initial = HERE / 'evidence/startup-targeted'
    follow = HERE / 'evidence/startup-followup'
    names = {
        'inittab': initial / 'etc__inittab', 'rcS': initial / 'etc__init.d__rcS',
        'rc': initial / 'etc__init.d__rc', 'fstab': initial / 'etc__fstab',
        'init_link': initial / '00.stdout.raw', 'rcS_listing': initial / '04.stdout.raw',
        'rc5_listing': initial / '05.stdout.raw', 'mountall': follow / 'etc__init.d__mountall.sh',
        'init_elf': follow / 'sbin__init.sysvinit', 'rc0_stat': follow / '00.stdout.raw',
        'rc6_stat': follow / '01.stdout.raw', 'mountall_link': follow / '02.stdout.raw',
    }
    raw = {key: read_regular(path) for key, path in names.items()}
    text = {key: value.decode('utf-8', 'replace') for key, value in raw.items() if key != 'init_elf'}
    require('Fast link dest: "/sbin/init.sysvinit"' in text['init_link'], 'Actual init target unknown')
    require(raw['init_elf'][:6] == b'\x7fELF\x01\x01' and struct.unpack_from('<H', raw['init_elf'], 18)[0] == 40,
            'SysV init is not the expected ARM32 ELF')
    require(re.search(r'^id:5:initdefault:$', text['inittab'], re.M) and
            re.search(r'^si::sysinit:/etc/init.d/rcS$', text['inittab'], re.M) and
            re.search(r'^l5:5:wait:/etc/init.d/rc 5$', text['inittab'], re.M), 'SysV default chain unknown')
    require('exec /etc/init.d/rc S' in text['rcS'] and
            'for i in /etc/rc$runlevel.d/S*' in text['rc'] and 'startup $i start' in text['rc'], 'RC dispatch unknown')
    require('/dev/mmcblk0p40    /mnt/userdata    ext4' in text['fstab'] and
            '/mnt/userdata/data    /mnt/data    none' in text['fstab'] and
            'mount -at nonfs,nosmbfs,noncpfs' in text['mountall'] and
            'S04mountall.sh' in text['rcS_listing'] and 'Fast link dest: "../init.d/mountall.sh"' in text['mountall_link'],
            'Data mount-before-rc5 chain unknown')
    require('S09weston' in text['rc5_listing'] and 'S90control_engine-init' in text['rc5_listing'] and
            'S96zybz03qt-init' in text['rc5_listing'], 'Stock service order unknown')
    require('Type: directory' in text['rc0_stat'] and 'Type: directory' in text['rc6_stat'], 'Shutdown rc directories missing')
    require('p011-bili-system' not in text['rc5_listing'], 'Startup entry already exists in original')
    return {key: dict(file=str(names[key].relative_to(HERE)), bytes=len(value), sha256=sha(value)) for key, value in raw.items()}


def patch_qrc(original, release_id, decode_module):
    require(sha(original) == decode_module.PIN, 'Original Z03 identity differs')
    before = decode_module.resource_map(original)
    target = before[decode_module.RESOURCE]
    require((target['offset'], target['size'], target['flags']) == (0x22a578, 3183, 1), 'Feedback slot differs')
    require(sha(target['body']) == decode_module.RESOURCE_PIN and
            sha(before[decode_module.SET_MAIN]['body']) == decode_module.SET_MAIN_PIN, 'Original settings identity differs')
    qml = decode_module.feedback_wrapper(release_id)
    old_url = ('file:///mnt/data/p011-toolbox/bili-formal/releases/' + release_id).encode('ascii')
    require(qml.count(old_url) == 1, 'Wrapper path count differs')
    qml = qml.replace(old_url, ('file:///opt/p011-bili/releases/' + release_id).encode('ascii'))
    packed = struct.pack('>I', len(qml)) + zlib.compress(qml, 9)
    require(len(packed) <= target['size'], 'Feedback slot overflow')
    offset, size = target['offset'], target['size']
    block = struct.pack('>I', len(packed)) + packed + bytes(size - len(packed))
    candidate = original[:offset] + block + original[offset + 4 + size:]
    after = decode_module.resource_map(candidate)
    changed = [name for name in before if before[name]['body'] != after[name]['body']]
    require(changed == [decode_module.RESOURCE] and len(candidate) == len(original), 'Unexpected QRC differences')
    require(before[decode_module.SET_MAIN] == after[decode_module.SET_MAIN] and
            original[:offset] == candidate[:offset] and original[offset+4+size:] == candidate[offset+4+size:],
            'Original entry or executable bytes changed')
    return candidate, dict(resources_verified=400, other_resources_unchanged=399,
        changed_resource=decode_module.RESOURCE, settings_entry_unchanged=True,
        outside_resource_record_unchanged=True, bytes=len(candidate), sha256=sha(candidate),
        new_feedback_source='file:///opt/p011-bili/releases/' + release_id + '/app/FeedbackEntry.qml')


def main():
    evidence = startup_evidence()
    manifest_raw = read_regular(PACKAGE / 'manifest.json')
    require(sha(manifest_raw) == PINNED_MANIFEST, 'Old formal manifest differs')
    inherited = json.loads(manifest_raw)
    incoming = {}
    for name, row in inherited.items():
        require(re.fullmatch(r'(?:app/[A-Za-z0-9_.+-]+|media/(?:bin|lib)(?:/gst)?/[A-Za-z0-9_.+-]+|media/manifest.json|source-manifest.json|Z03.patched)', name),
                'Inherited path outside payload')
        raw = read_regular(PACKAGE / name)
        require(len(raw) == row['bytes'] and sha(raw) == row['sha256'], 'Inherited payload differs: ' + name)
        incoming[name] = raw
    sources = {name: sha(read_regular(HERE / name)) for name in SOURCE_NAMES}
    decode_module = decoder()
    inputs = dict(schema='p011.system-layout.inputs.v1', sources=sources, startup_evidence=evidence,
                  base_system_sha256=IMAGE_SHA, inherited_manifest_sha256=PINNED_MANIFEST,
                  inherited_release=OLD_ID, qrc_decoder_sha256=sha(read_regular(FORMAL / 'host/build_formal.py')),
                  immutable_base='/opt/p011-bili/releases', mutable_base='/mnt/data/p011-toolbox',
                  startup_chain='SysV default5, S99p011-bili-system; K05 in rc0/rc6')
    release_id = sha(canonical(inputs))[:24]
    require(release_id != OLD_ID, 'New layout must have a new identity')
    release = '/opt/p011-bili/releases/' + release_id
    out = HERE / 'out' / release_id
    out.mkdir(parents=True, exist_ok=False)
    root = out / 'system-files'
    files = {}
    mutable_changed = []
    for name, raw in incoming.items():
        if not name.startswith(('app/', 'media/')):
            continue
        if name in ('app/BiliPanel.qml', 'app/Bridge.qml', 'app/config.py'):
            require(OLD_ID.encode('ascii') in raw, 'Missing old runtime identity: ' + name)
            raw = raw.replace(OLD_ID.encode('ascii'), release_id.encode('ascii'))
            if name == 'app/config.py':
                old_release = ('/mnt/data/p011-toolbox/bili-formal/releases/' + release_id).encode('ascii')
                require(raw.count(old_release) == 2, 'App/media path substitution count differs')
                raw = raw.replace(old_release, release.encode('ascii'))
            mutable_changed.append(name)
        files[release + '/' + name] = raw
    bootstrap = read_regular(HERE / 'system_bootstrap.py.in').replace(b'@RELEASE_ID@', release_id.encode('ascii'))
    init = read_regular(HERE / 'init-script.sh.in').replace(b'@RELEASE_ID@', release_id.encode('ascii'))
    files[release + '/system_bootstrap.py'] = bootstrap
    files['/etc/init.d/p011-bili-system'] = init
    original = read_regular(PROJECT / '06_Firmware/backups/v2.4.0-20260923-162730/files/Z03')
    files['/usr/bin/Z03'], qrc = patch_qrc(original, release_id, decode_module)
    manifest = {}
    for path, raw in sorted(files.items()):
        destination = root / path.lstrip('/')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        executable = path.startswith(release + '/media/bin/') or path == '/etc/init.d/p011-bili-system'
        mode = '0755' if executable else '0644'
        if path == '/usr/bin/Z03':
            mode = '0755'
        manifest[path] = dict(kind='file', bytes=len(raw), sha256=sha(raw), mode=mode, uid=0, gid=0,
                              overlay_file=str(destination.relative_to(out)).replace('\\', '/'))
        if path.endswith('.py'):
            ast.parse(raw.decode('utf-8'), filename=path, feature_version=(3, 5))
    links = {name: '../init.d/p011-bili-system' for name in (
        '/etc/rc5.d/S99p011-bili-system', '/etc/rc0.d/K05p011-bili-system', '/etc/rc6.d/K05p011-bili-system')}
    for path, target in links.items():
        manifest[path] = dict(kind='symlink', target=target, mode='0777', uid=0, gid=0)
    # Preserve source notices while keeping credentials and mutable state out.
    require(all(not path.startswith(('/mnt/', '/home/', '/var/', '/etc/productinfo/')) for path in manifest),
            'Mutable/device-specific data reached overlay')
    plan = dict(status='HOST_LAYOUT_CANDIDATE_NOT_IMAGE_NOT_FLASHED', release_id=release_id,
                firmware='z031_v2.4.0-20251128_174826-user', base_system_sha256=IMAGE_SHA,
                old_formal_release=OLD_ID, old_formal_package_modified=False, original_image_modified=False,
                image_built=False, target_code_executed=False, device_tested=False, adb_invoked=False,
                userdata_cloned=False, nv_cloned=False, immutable_release=release,
                runtime='/mnt/data/p011-toolbox/bili-awake/' + release_id,
                data_first_creation='Own directories only after unique writable p40 /mnt/data check; preserve existing account/library/preferences',
                init_kind='sysvinit', startup_link='/etc/rc5.d/S99p011-bili-system',
                stock_init_files_modified=False, inherited_payload_files_verified=len(incoming),
                inherited_text_changed=mutable_changed, qrc=qrc, files_manifest_sha256=sha(canonical(manifest)),
                member_count=len(manifest), overlay_bytes=sum(len(raw) for raw in files.values()),
                symlinks_materialized=False, symlink_application='Manifest only; future image builder must apply exact links',
                pending=['current target non-ADB system identity and backup/readback',
                         'accepted bounded write and verified restore path', 'candidate image construction/verification',
                         'real init/data mount/loopback/UI/exit/reboot/stock business acceptance', 'portable cross-PC packaging'])
    (out / 'source-inputs.json').write_bytes(canonical(inputs))
    (out / 'files-manifest.json').write_bytes(canonical(manifest))
    (out / 'layout-plan.json').write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding='utf-8')
    (out / 'SHA256SUMS.txt').write_text('\n'.join(row['sha256'] + '  ' + row['overlay_file']
        for path, row in sorted(manifest.items()) if row['kind'] == 'file') + '\n', encoding='ascii')
    print(json.dumps(dict(output=str(out), release_id=release_id, qrc=qrc,
                         status=plan['status'], member_count=len(manifest), overlay_bytes=plan['overlay_bytes']), indent=2))


if __name__ == '__main__':
    main()
