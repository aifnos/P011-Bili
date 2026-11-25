"""Recognize a verified restored release, preserve it, then allow reinstall."""


def retained_layout(meta, helper_sha=None):
    rid=meta['release_id']
    require(re.match(r'^[a-f0-9]{24}$',rid), 'retained release identity invalid')
    release=FORMAL+'/releases/'+rid
    runtime=AREA+'/bili-awake/'+rid
    present=(os.path.lexists(release),os.path.lexists(runtime))
    if present == (False,False):return dict(present=False)
    require(present == (True,True), 'incomplete retained release/runtime; original files preserved')
    require(not os.path.lexists(FORMAL+'/install-receipt.json'), 'active installation cannot be archived')
    directory(release);directory(runtime)
    # A previous formal package provides this exact bundled standard library.
    # A fresh device returns above and does not need a target json module.
    regular(release+'/app/stdlib-json35.zip')
    require(digest(release+'/app/stdlib-json35.zip') == REINSTALL_JSON_SHA,
            'retained JSON runtime identity differs')
    sys.path.insert(0,release+'/app/stdlib-json35.zip')
    import json
    manifest_sha=digest(release+'/manifest.json')
    require(manifest_sha in (meta['manifest_sha256'], REINSTALL_LEGACY_MANIFEST_SHA),
            'unknown retained manifest; original files preserved')
    manifest=json.loads(read(release+'/manifest.json').decode('ascii'))
    require(isinstance(manifest,dict) and 'Z03.patched' in manifest, 'retained manifest schema')
    for name,row in manifest.items():
        require(re.match(r'^(?:app/[A-Za-z0-9_.+-]+|media/(?:bin|lib)(?:/gst)?/[A-Za-z0-9_.+-]+|media/manifest.json|source-manifest.json|Z03.patched)$',name),
                'retained payload path refused')
        if name=='Z03.patched':continue
        regular(release+'/'+name)
        require(os.path.getsize(release+'/'+name)==row['bytes'] and
                digest(release+'/'+name)==row['sha256'], 'retained payload drift: '+name)
    old_meta=json.loads(read(release+'/build-result.json').decode('ascii'))
    require(old_meta.get('release_id')==rid and old_meta.get('patched_sha256')==meta['patched_sha256'] and
            old_meta.get('manifest_sha256')==manifest_sha, 'retained metadata differs')
    regular(release+'/device_install.py')
    current_helper=helper_sha or digest(BASE+'/device_install.py')
    require(digest(release+'/device_install.py') in REINSTALL_LEGACY_HELPERS+(current_helper,),
            'unknown retained installer helper')
    proofs=[]
    for name in sorted(os.listdir(FORMAL+'/backups')):
        if not re.match('^'+rid+r'-[0-9]{8}-[0-9]{6}$',name):continue
        backup=FORMAL+'/backups/'+name
        receipt_path=backup+'/restored-install-receipt.json'
        restore_path=backup+'/restore-result.json'
        if not os.path.isfile(receipt_path) or not os.path.isfile(restore_path):continue
        directory(backup);regular(receipt_path);regular(restore_path)
        receipt=json.loads(read(receipt_path).decode('ascii'))
        restored=json.loads(read(restore_path).decode('ascii'))
        if (receipt.get('release_id')==rid and receipt.get('release')==release and
            receipt.get('runtime')==runtime and receipt.get('patched_sha256')==meta['patched_sha256'] and
            restored.get('restored') is True and restored.get('root_mount_restored') is True):
            regular(backup+'/Z03.original')
            require(digest(backup+'/Z03.original')==PINS[TARGET], 'retained original backup differs')
            proofs.append(dict(receipt=receipt_path,receipt_sha256=digest(receipt_path),
                               restore=restore_path,restore_sha256=digest(restore_path)))
    require(proofs, 'retained directories have no verified successful restore record')
    count=0
    for base in (release,runtime):
        for root,dirs,files in os.walk(base,followlinks=False):
            for name in dirs+files:
                path=root+'/'+name
                info=os.lstat(path)
                require(info.st_uid==0 and (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)),
                        'unsafe retained descendant; original files preserved')
                count+=1
                require(count<=4096, 'retained entry count exceeded; original files preserved')
    return dict(present=True,release=release,runtime=runtime,manifest_sha256=manifest_sha,
                helper_sha256=digest(release+'/device_install.py'),proofs=proofs,entries=count)


def archive_retained_layout(meta, expected, backup):
    if not expected['present']:return None
    current=retained_layout(meta)
    require(current==expected, 'retained layout changed before preservation')
    directory(backup)
    retired=FORMAL+'/retained'
    directory(retired,True)
    archive=retired+'/'+meta['release_id']+'-'+time.strftime('%Y%m%d-%H%M%S')+'-'+os.urandom(4).hex()
    require(not os.path.lexists(archive), 'retained archive already exists')
    directory(archive,True)
    journal=dict(archive=archive,source=current,release_moved=False,runtime_moved=False,
                 preserved=False,rollback_complete=False)
    save(archive+'/preservation.json',journal)
    moved=[]
    try:
        for name in ('release','runtime'):
            source=current[name]
            target=archive+'/'+name
            require(source in (FORMAL+'/releases/'+meta['release_id'],AREA+'/bili-awake/'+meta['release_id']) and
                    os.path.realpath(source)==source and os.path.normpath(target)==target and
                    target.startswith(retired+'/'), 'retained move escaped fixed area')
            require(not os.path.lexists(target), 'retained destination appeared')
            os.rename(source,target)
            moved.append((source,target))
            journal[name+'_moved']=True
            save(archive+'/preservation.json',journal)
        require(digest(archive+'/release/manifest.json')==current['manifest_sha256'], 'preserved manifest differs')
        require(not os.path.lexists(current['release']) and not os.path.lexists(current['runtime']),
                'retained paths still occupied')
        journal['preserved']=True
        save(archive+'/preservation.json',journal)
        save(backup+'/retained-preservation.json',journal)
        return journal
    except BaseException as exc:
        journal['error']=type(exc).__name__+': '+str(exc)
        try:
            for source,target in reversed(moved):
                require(not os.path.lexists(source) and os.path.lexists(target), 'retained rollback conflict')
                os.rename(target,source)
            journal['rollback_complete']=True
        except BaseException as rollback_error:
            journal['rollback_error']=type(rollback_error).__name__+': '+str(rollback_error)
        save(archive+'/preservation.json',journal)
        raise
