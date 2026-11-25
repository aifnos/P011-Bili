"""Offline image build inside pinned Docker; original mounted read-only."""
import hashlib
import json
import os
import pathlib
import shutil
import stat
import subprocess

BASE = pathlib.Path('/original/p29-system.img')
OVERLAY = pathlib.Path('/overlay')
OUT = pathlib.Path('/out')
PIN = '6bf4706e5f03ed79edfe0e4ab337dbcc1310d6a7b57116a09ecfa756b4de648f'
Z03 = 'cb8d6a78617d50f64c6adc8056427dd963bc83979cbb04e349275dd8e8ffb62a'


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1048576), b''):
            digest.update(chunk)
    return digest.hexdigest()


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def command(label, argv):
    result = subprocess.run(argv, capture_output=True)
    (OUT / (label + '.stdout.raw')).write_bytes(result.stdout)
    (OUT / (label + '.stderr.raw')).write_bytes(result.stderr)
    (OUT / (label + '.exit.txt')).write_text(str(result.returncode))
    require(result.returncode == 0, label + ' failed; inspect raw logs')
    return result.stdout


def tree(folder):
    result = {}
    for parent, dirs, files in os.walk(folder, followlinks=False):
        for name in dirs + files:
            path = pathlib.Path(parent) / name
            meta = path.lstat()
            row = dict(mode=stat.S_IMODE(meta.st_mode), uid=meta.st_uid, gid=meta.st_gid)
            if stat.S_ISLNK(meta.st_mode):
                row.update(kind='symlink', target=os.readlink(path))
            elif stat.S_ISDIR(meta.st_mode):
                row['kind'] = 'directory'
            elif stat.S_ISREG(meta.st_mode):
                row.update(kind='file', bytes=meta.st_size, sha256=sha(path))
            else:
                row.update(kind='special', mode_type=stat.S_IFMT(meta.st_mode), rdev=meta.st_rdev)
            result['/' + path.relative_to(folder).as_posix()] = row
    return result


def main():
    require(BASE.stat().st_size == 1073741824 and sha(BASE) == PIN, 'original image identity mismatch')
    manifest = json.loads((OVERLAY / 'files-manifest.json').read_bytes())
    plan = json.loads((OVERLAY / 'layout-plan.json').read_bytes())
    for name, row in manifest.items():
        require(name.startswith('/') and '..' not in name.split('/'), 'invalid overlay path')
        if row['kind'] == 'file':
            path = OVERLAY / row['overlay_file']
            require(path.stat().st_size == row['bytes'] and sha(path) == row['sha256'], 'overlay hash mismatch: ' + name)
    prior = pathlib.Path('/prior')
    if prior.is_dir():
        require((prior / 'original-fsck.exit.txt').read_text() == '0' and
                (prior / 'original-rdump.exit.txt').read_text() == '0', 'prior baseline did not pass')
        print('STAGE=REUSE_VERIFIED_ORIGINAL_TREE', flush=True)
        before = json.loads((prior / 'original-tree.json').read_bytes())
        original_z03 = (pathlib.Path('/original/files/Z03')).read_bytes()
        require(hashlib.sha256(original_z03).hexdigest() == before['/usr/bin/Z03']['sha256'], 'saved original differs')
    else:
        print('STAGE=ORIGINAL_FSCK_AND_TREE', flush=True)
        command('original-fsck', ['e2fsck', '-f', '-n', str(BASE)])
        original_tree = pathlib.Path('/tmp/p011-original-tree')
        original_tree.mkdir()
        command('original-rdump', ['debugfs', '-R', 'rdump / ' + str(original_tree), str(BASE)])
        before = tree(original_tree)
        original_z03 = (original_tree / 'usr/bin/Z03').read_bytes()
    (OUT / 'original-tree.json').write_text(json.dumps(before, indent=2))
    require(before['/usr/bin/Z03']['sha256'] == Z03, 'original Z03 differs')
    target = OUT / 'system-bili.img'
    require(not target.exists(), 'refusing to replace candidate image')
    shutil.copyfile(BASE, target)
    candidate_z03 = (OVERLAY / manifest['/usr/bin/Z03']['overlay_file']).read_bytes()
    offset, extent = 0x22a578, 3187
    require(len(original_z03) == len(candidate_z03) and
            original_z03[:offset] == candidate_z03[:offset] and
            original_z03[offset + extent:] == candidate_z03[offset + extent:], 'QRC differs outside allowed record')
    block_bytes = 4096
    changed_blocks = []
    print('STAGE=APPLY_EXACT_OVERLAY', flush=True)
    with target.open('r+b') as image:
        for logical in range(offset // block_bytes, (offset + extent - 1) // block_bytes + 1):
            physical = int(command('z03-bmap-' + str(logical),
                ['debugfs', '-R', 'bmap /usr/bin/Z03 ' + str(logical), str(BASE)]).strip())
            require(physical > 0, 'Z03 sparse/unmapped block')
            image.seek(physical * block_bytes)
            old = image.read(block_bytes)
            require(old == original_z03[logical * block_bytes:(logical + 1) * block_bytes], 'bmap bytes differ')
            image.seek(physical * block_bytes)
            image.write(candidate_z03[logical * block_bytes:(logical + 1) * block_bytes])
            changed_blocks.append(dict(logical=logical, physical=physical))
        image.flush()
        os.fsync(image.fileno())
    directories = set()
    for name in manifest:
        parent = pathlib.PurePosixPath(name).parent
        while str(parent) != '/':
            directories.add(str(parent))
            parent = parent.parent
    commands = []
    added_dirs = sorted(directories - set(before), key=lambda x: (x.count('/'), x))
    for name in added_dirs:
        commands += ['mkdir ' + name, 'set_inode_field ' + name + ' mode 040755',
                     'set_inode_field ' + name + ' uid 0', 'set_inode_field ' + name + ' gid 0']
    for name, row in sorted(manifest.items()):
        if name == '/usr/bin/Z03':
            continue
        require(name not in before, 'unexpected overwrite: ' + name)
        if row['kind'] == 'file':
            commands += ['write ' + str(OVERLAY / row['overlay_file']) + ' ' + name,
                         'set_inode_field ' + name + ' mode 010' + row['mode']]
        else:
            commands += ['symlink ' + name + ' ' + row['target']]
        commands += ['set_inode_field ' + name + ' uid 0', 'set_inode_field ' + name + ' gid 0']
    batch = OUT / 'debugfs-apply.txt'
    batch.write_text('\n'.join(commands) + '\n')
    command('apply', ['debugfs', '-w', '-f', str(batch), str(target)])
    command('candidate-fsck', ['e2fsck', '-f', '-n', str(target)])
    print('STAGE=VERIFY_FULL_FILESYSTEM_DIFF', flush=True)
    after_tree = pathlib.Path('/tmp/p011-candidate-tree')
    after_tree.mkdir()
    command('candidate-rdump', ['debugfs', '-R', 'rdump / ' + str(after_tree), str(target)])
    after = tree(after_tree)
    (OUT / 'candidate-tree.json').write_text(json.dumps(after, indent=2))
    changed = [name for name in before if before[name] != after.get(name)]
    added = sorted(set(after) - set(before))
    require(changed == ['/usr/bin/Z03'], 'unexpected original filesystem changes: ' + repr(changed))
    require(set(added) == (set(manifest) - {'/usr/bin/Z03'}) | set(added_dirs), 'unexpected added filesystem paths')
    for name, row in manifest.items():
        current = after[name]
        require(current['kind'] == row['kind'] and current['mode'] == int(row['mode'], 8) and
                current['uid'] == row['uid'] and current['gid'] == row['gid'], 'metadata mismatch: ' + name)
        for key in ('bytes', 'sha256') if row['kind'] == 'file' else ('target',):
            require(current[key] == row[key], 'candidate content mismatch: ' + name)
    require(sha(BASE) == PIN, 'original image changed')
    result = dict(status='HOST_FULL_SYSTEM_IMAGE_VERIFIED_DEVICE_PENDING',
        base_sha256=PIN, candidate_sha256=sha(target), bytes=target.stat().st_size,
        release_id=plan['release_id'], original_entries_verified=len(before),
        changed_existing_paths=changed, added_paths=added, z03_blocks_patched_in_place=changed_blocks,
        original_z03_inode_preserved=True, fsck_original_exit=0, fsck_candidate_exit=0,
        original_unchanged=True, userdata_included=False, nv_included=False,
        added_font_files=False, device_tested=False, qrc=plan['qrc'])
    (OUT / 'image-result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
