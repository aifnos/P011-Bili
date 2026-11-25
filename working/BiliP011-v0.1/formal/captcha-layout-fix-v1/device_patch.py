"""Five-file QML repair, executed with the pinned formal-install helpers.

Python 3.5 compatible. No process restart or system-file write is performed.
"""


def qml_gate(require_idle=False):
    meta, rid, release, runtime = metadata()
    require(rid == PATCH['release_id'] and BASE == release,
            'installed release location differs')
    directory(release)
    receipt_path = FORMAL + '/install-receipt.json'
    regular(receipt_path)
    receipt = json.loads(read(receipt_path).decode('ascii'))
    require(receipt.get('installed') is True and receipt.get('release_id') == rid and
            receipt.get('patched_sha256') == PATCH['patched_sha256'],
            'installation receipt differs')
    require(receipt['backup'].startswith(FORMAL + '/backups/' + rid + '-'),
            'original backup location differs')
    directory(receipt['backup'])
    require(digest(receipt['backup'] + '/Z03.original') == PINS[TARGET],
            'original Z03 backup differs')
    live = live_gate(PATCH['patched_sha256'], True)
    require(receipt['startup'] == live['startup'] and
            digest(live['startup']['path']) == receipt['startup_sha256'],
            'installed startup identity differs')
    require(len(service_rows(release)) == 1, 'one formal service required')
    lease_path = runtime + '/lease.json'
    regular(lease_path)
    lease = json.loads(read(lease_path).decode('ascii'))
    require(lease.get('session') == rid and isinstance(lease.get('active'), bool),
            'formal session lease differs')
    players = [r for r in processes()
               if os.path.basename(r['exe']) in ('bili-player', 'bili-hw')]
    idle = lease['active'] is False and not players
    if require_idle:
        require(idle, 'exit the Bili page and wait for its session cleanup first')
    return receipt, live, runtime, idle


def qml_verify_payload(state):
    require(state in ('before', 'after'), 'verification state differs')
    expected = PATCH[state]
    for name, row in expected.items():
        regular(BASE + '/' + name)
        require(os.path.getsize(BASE + '/' + name) == row['bytes'] and
                digest(BASE + '/' + name) == row['sha256'],
                'UI patch target differs: ' + name)
    meta = json.loads(read(BASE + '/build-result.json').decode('ascii'))
    require(meta.get('release_id') == PATCH['release_id'] and
            meta.get('source_identity_sha256') == PATCH['base_source_identity_sha256'] and
            meta.get('patched_sha256') == PATCH['patched_sha256'],
            'compatible base identity changed')
    require(digest(BASE + '/manifest.json') == meta['manifest_sha256'],
            'installed metadata to manifest link differs')
    manifest = json.loads(read(BASE + '/manifest.json').decode('ascii'))
    require(isinstance(manifest, dict) and sorted(manifest) == PATCH['manifest_keys'],
            'installed manifest membership differs')
    for name, row in manifest.items():
        require(re.match(r'^(?:app/[A-Za-z0-9_.+-]+|media/(?:bin|lib)(?:/gst)?/[A-Za-z0-9_.+-]+|media/manifest.json|source-manifest.json|Z03.patched)$', name),
                'untrusted manifest path')
        path = TARGET if name == 'Z03.patched' else BASE + '/' + name
        regular(path)
        require(os.path.getsize(path) == row['bytes'] and digest(path) == row['sha256'],
                'installed payload drift: ' + name)
    source_manifest = json.loads(read(BASE + '/source-manifest.json').decode('ascii'))
    for name, row in PATCH['source_records'][state].items():
        require(source_manifest.get('client/' + name) == row,
                'QML source provenance differs: ' + name)
    if state == 'after':
        require(meta.get('ui_patch_revision') == PATCH['revision_sha256'],
                'UI metadata revision differs')
    return dict(manifest_sha256=digest(BASE + '/manifest.json'),
                payload_files_verified=len(manifest), source_records_verified=2)


def qml_inspect():
    receipt, live, runtime, idle = qml_gate()
    check = qml_verify_payload('before')
    require('ui_patch' not in receipt, 'an installed UI patch already exists')
    return dict(ready=idle, session_idle=idle, release_id=PATCH['release_id'],
                payload=check, device_files_replaced=False,
                physical_acceptance=False, ui_restart_required_after_apply=True)


def qml_verify():
    receipt, live, runtime, idle = qml_gate()
    check = qml_verify_payload('after')
    entry = receipt.get('ui_patch', {})
    require(entry.get('revision') == PATCH['revision_sha256'] and
            entry.get('files') == {name: PATCH['after'][name]['sha256']
                                   for name in PATCH['qml_paths']},
            'UI patch receipt differs')
    backup = receipt['backup'] + '/captcha-layout-' + PATCH['revision_sha256'][:24]
    require(entry.get('backup') == backup, 'UI patch backup receipt differs')
    directory(backup)
    for name, row in PATCH['before'].items():
        regular(backup + '/' + name)
        require(digest(backup + '/' + name) == row['sha256'],
                'UI patch original backup differs')
    regular(backup + '/install-receipt.before.json')
    require(digest(backup + '/install-receipt.before.json') == entry.get('before_receipt_sha256'),
            'original installation receipt backup differs')
    return dict(verified=True, release_id=PATCH['release_id'],
                revision=PATCH['revision_sha256'], payload=check,
                session_idle=idle, physical_acceptance=False,
                ui_restart_or_reopen_verified=False)


def qml_apply():
    lock = transaction_lock()
    written = []
    backup = None
    before_receipt = None
    committed_receipt = None
    result = dict(applied=False, rolled_back=False, physical_acceptance=False,
                  system_files_changed=False, process_restart_performed=False,
                  revision=PATCH['revision_sha256'])
    try:
        receipt, live, runtime, idle = qml_gate(True)
        qml_verify_payload('before')
        require('ui_patch' not in receipt, 'an installed UI patch already exists')
        before_receipt = read(FORMAL + '/install-receipt.json')
        stage = FORMAL + '/ui-patches/' + PATCH['revision_sha256'][:24]
        directory(stage)
        for name, row in PATCH['after'].items():
            directory(os.path.dirname(stage + '/' + name))
            regular(stage + '/' + name)
            require(digest(stage + '/' + name) == row['sha256'] and
                    os.path.getsize(stage + '/' + name) == row['bytes'],
                    'staged UI patch differs: ' + name)
        planned_backup = receipt['backup'] + '/captcha-layout-' + PATCH['revision_sha256'][:24]
        require(not os.path.lexists(planned_backup), 'prior UI patch transaction exists; inspect it first')
        directory(planned_backup, True)
        backup = planned_backup
        result['backup'] = backup
        atomic(backup + '/install-receipt.before.json', before_receipt, 0o600)
        for name, row in PATCH['before'].items():
            directory(os.path.dirname(backup + '/' + name), True)
            atomic(backup + '/' + name, read(BASE + '/' + name, 16777216), 0o600)
            require(digest(backup + '/' + name) == row['sha256'], 'UI backup readback differs')
        save(backup + '/transaction.json', result)
        for name in PATCH['order']:
            qml_gate(True)
            require(digest(BASE + '/' + name) == PATCH['before'][name]['sha256'],
                    'target changed immediately before UI write')
            result['next_file'] = name
            save(backup + '/transaction.json', result)
            written.append(name)
            mode = stat.S_IMODE(os.stat(BASE + '/' + name).st_mode)
            atomic(BASE + '/' + name, read(stage + '/' + name, 16777216), mode)
            require(digest(BASE + '/' + name) == PATCH['after'][name]['sha256'],
                    'UI write readback differs')
        qml_verify_payload('after')
        require(read(FORMAL + '/install-receipt.json') == before_receipt,
                'installation receipt changed during UI patch')
        receipt['ui_patch'] = dict(revision=PATCH['revision_sha256'], backup=backup,
            before_receipt_sha256=hashlib.sha256(before_receipt).hexdigest(),
            files={name: PATCH['after'][name]['sha256'] for name in PATCH['qml_paths']})
        committed_receipt = json.dumps(receipt, sort_keys=True, indent=2).encode('ascii')
        atomic(FORMAL + '/install-receipt.json', committed_receipt, 0o600)
        _, after, _, _ = qml_gate(True)
        require(all(after[key] == live[key] for key in ('boot', 'mounts', 'startup')) and
                all(after[row][key] == live[row][key]
                    for row in ('app', 'launcher')
                    for key in ('pid', 'parent', 'start', 'exe', 'args')),
                'stock process, startup or mount identity changed')
        result.update(applied=True, verified=qml_verify(),
                      original_system_and_processes_unchanged=True,
                      ui_restart_required=True)
        save(backup + '/transaction.json', result)
    except BaseException as exc:
        result['applied'] = False
        result['error'] = type(exc).__name__ + ': ' + str(exc)
        if backup is not None:
            try:
                for name in reversed(written):
                    require(digest(BASE + '/' + name) in
                            (PATCH['before'][name]['sha256'], PATCH['after'][name]['sha256']),
                            'refusing rollback of externally changed UI file')
                    mode = stat.S_IMODE(os.stat(BASE + '/' + name).st_mode)
                    atomic(BASE + '/' + name, read(backup + '/' + name, 16777216), mode)
                    require(digest(BASE + '/' + name) == PATCH['before'][name]['sha256'],
                            'UI rollback readback differs')
                receipt_now = read(FORMAL + '/install-receipt.json')
                require(receipt_now in (before_receipt, committed_receipt),
                        'refusing rollback of externally changed receipt')
                atomic(FORMAL + '/install-receipt.json', before_receipt, 0o600)
                result['rolled_back'] = True
            except BaseException as rollback_error:
                result['rollback_error'] = type(rollback_error).__name__ + ': ' + str(rollback_error)
        raise
    finally:
        try:
            if backup is not None and not result['applied']:
                try:
                    save(backup + '/transaction.json', result)
                except BaseException as journal_error:
                    result['journal_error'] = type(journal_error).__name__ + ': ' + str(journal_error)
        finally:
            os.close(lock)
            print('RESULT=' + repr(result), flush=True)
    return result
