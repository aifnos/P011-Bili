"""Fixed seven-file worker hotfix. Loaded after the pinned install helpers."""


def playback_gate():
    meta, rid, release, runtime = metadata()
    require(rid == PATCH['release_id'], 'installed release differs')
    require(BASE == release, 'fixed release location required')
    receipt_path = FORMAL + '/install-receipt.json'
    regular(receipt_path)
    receipt = json.loads(read(receipt_path).decode('utf8'))
    require(receipt.get('installed') is True and receipt.get('release_id') == rid and
            receipt.get('patched_sha256') == PATCH['patched_sha256'], 'receipt differs')
    directory(receipt['backup'])
    require(receipt['backup'].startswith(FORMAL+'/backups/'+rid+'-'), 'backup location differs')
    require(digest(receipt['backup']+'/Z03.original') == PINS[TARGET], 'original backup differs')
    live = live_gate(PATCH['patched_sha256'], True)
    require(receipt['startup'] == live['startup'] and
            digest(live['startup']['path']) == receipt['startup_sha256'], 'startup differs')
    require(len(service_rows(release)) == 1, 'one installed service required')
    for row in processes():
        require(os.path.basename(row['exe']) not in ('bili-player', 'bili-hw'),
                'exit Bili playback before applying patch')
    return receipt, live, runtime


def worker_selftest(release, runtime):
    env = {k:v for k,v in os.environ.items() if not k.startswith(('LD_', 'GST_'))}
    env.update(GST_PLUGIN_PATH_1_0=release+'/media/lib/gst',
               GST_REGISTRY=runtime+'/gst-playback-patch-registry.bin',
               GST_REGISTRY_FORK='no', GST_DEBUG='0')
    child = subprocess.Popen([release+'/media/bin/bili-hw', '--preflight'],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    try:
        stdout, stderr = child.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        child.terminate()
        try: stdout, stderr = child.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
            stdout, stderr = child.communicate()
        raise RuntimeError('fixed worker preflight timed out')
    rows = [line for line in stdout.splitlines() if line.startswith(b'{')]
    require(len(rows) == 1, 'worker preflight result missing')
    value = json.loads(rows[0].decode('ascii'))
    require(isinstance(value, dict), 'worker preflight schema')
    return dict(exit=child.returncode, result=value, stderr_bytes=len(stderr))


def verify_old_payload():
    require(digest(BASE+'/manifest.json') == PATCH['before']['manifest.json']['sha256'],
            'installed manifest differs')
    manifest = json.loads(read(BASE+'/manifest.json').decode('ascii'))
    for name, spec in manifest.items():
        if name == 'Z03.patched': continue
        regular(BASE+'/'+name)
        require(os.path.getsize(BASE+'/'+name) == spec['bytes'] and
                digest(BASE+'/'+name) == spec['sha256'], 'installed payload drift: '+name)
    for name, spec in PATCH['before'].items():
        regular(BASE+'/'+name)
        require(digest(BASE+'/'+name) == spec['sha256'], 'patch target drift: '+name)


def playback_inspect():
    receipt, live, runtime = playback_gate()
    verify_old_payload()
    test = worker_selftest(BASE, runtime)
    return dict(ready=True, before_worker=test, boot=live['boot'],
                physical_acceptance=False, device_files_replaced=False)


def apply_playback_patch():
    lock = transaction_lock()
    written = []
    result = dict(applied=False, rolled_back=False, physical_acceptance=False,
                  partition_write=False, system_files_changed=False,
                  patch_revision=PATCH['revision_sha256'], file_replace_attempted=False)
    backup = None
    try:
        receipt, live, runtime = playback_gate()
        verify_old_payload()
        before_receipt = read(FORMAL+'/install-receipt.json')
        stage = FORMAL+'/playback-patches/'+PATCH['revision_sha256'][:24]
        directory(stage)
        for name, spec in PATCH['after'].items():
            regular(stage+'/'+name)
            require(digest(stage+'/'+name) == spec['sha256'] and
                    os.path.getsize(stage+'/'+name) == spec['bytes'], 'patch staging differs')
        backup = receipt['backup']+'/playback-fix-'+PATCH['revision_sha256'][:24]
        require(not os.path.lexists(backup), 'patch backup already exists; inspect prior transaction')
        directory(backup, True)
        atomic(backup+'/install-receipt.before.json', before_receipt, 0o600)
        for name, spec in PATCH['before'].items():
            directory(os.path.dirname(backup+'/'+name), True)
            atomic(backup+'/'+name, read(BASE+'/'+name, 16777216), 0o600)
            require(digest(backup+'/'+name) == spec['sha256'], 'patch backup readback differs')
        result.update(backup=backup, before_worker=worker_selftest(BASE, runtime))
        save(backup+'/transaction.json', result)
        # Keep metadata last; a failure restores the exact seven previous files.
        for name in PATCH['order']:
            playback_gate()
            require(digest(BASE+'/'+name) == PATCH['before'][name]['sha256'], 'target changed before write')
            result['file_replace_attempted'] = True
            result['next_file'] = name
            save(backup+'/transaction.json', result)
            written.append(name)
            mode = stat.S_IMODE(os.stat(BASE+'/'+name).st_mode)
            atomic(BASE+'/'+name, read(stage+'/'+name, 16777216), mode)
            require(digest(BASE+'/'+name) == PATCH['after'][name]['sha256'], 'patch write readback differs')
        test = worker_selftest(BASE, runtime)
        require(test['exit'] == 0 and test['result'].get('ok') is True,
                'fixed worker preflight failed')
        manifest = json.loads(read(BASE+'/manifest.json').decode('ascii'))
        for name, spec in manifest.items():
            if name == 'Z03.patched': continue
            require(digest(BASE+'/'+name) == spec['sha256'], 'post-patch manifest differs')
        current_receipt = read(FORMAL+'/install-receipt.json')
        require(current_receipt == before_receipt, 'receipt changed during patch')
        receipt['playback_patch'] = dict(revision=PATCH['revision_sha256'], backup=backup,
                                         worker_sha256=PATCH['after']['media/bin/bili-hw']['sha256'])
        save(FORMAL+'/install-receipt.json', receipt)
        _, after, _ = playback_gate()
        require(all(after[key] == live[key] for key in ('boot', 'mounts', 'startup')) and
                all(after[row][key] == live[row][key]
                    for row in ('app', 'launcher') for key in ('pid', 'parent', 'start', 'exe', 'args')),
                'stock identity or root mount changed')
        result.update(applied=True, after_worker=test, root_mount_unchanged=True,
                      stock_processes_unchanged=True, release_id=PATCH['release_id'])
    except BaseException as exc:
        result['error'] = type(exc).__name__+': '+str(exc)
        if backup is not None:
            try:
                for name in reversed(written):
                    current = digest(BASE+'/'+name)
                    require(current in (PATCH['before'][name]['sha256'], PATCH['after'][name]['sha256']),
                            'rollback target changed outside patch')
                    mode = stat.S_IMODE(os.stat(BASE+'/'+name).st_mode)
                    atomic(BASE+'/'+name, read(backup+'/'+name,16777216), mode)
                    require(digest(BASE+'/'+name) == PATCH['before'][name]['sha256'], 'rollback mismatch')
                atomic(FORMAL+'/install-receipt.json', read(backup+'/install-receipt.before.json'), 0o600)
                result['rolled_back'] = True
            except BaseException as rollback_error:
                result['rollback_error'] = type(rollback_error).__name__+': '+str(rollback_error)
        raise
    finally:
        if backup is not None: save(backup+'/transaction.json', result)
        os.close(lock)
        print('RESULT='+repr(result), flush=True)
    return result
