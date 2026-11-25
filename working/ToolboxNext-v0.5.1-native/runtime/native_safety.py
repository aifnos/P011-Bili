"""Narrow filesystem/process gates for the v2.4.0 independent UI trial."""
import hashlib
import os
import re

AREA='/mnt/data/p011-toolbox'
PINS={
    '/usr/bin/Z03':'cb8d6a78617d50f64c6adc8056427dd963bc83979cbb04e349275dd8e8ffb62a',
    '/usr/bin/control_engine':'364b0bf820799070e89d9362000de4a3796a0e6a2d5f4d657464c6385b8dbd6d',
    '/usr/bin/zyb_z03_launch.sh':'7bce5379e3cc78e5bd8c04ceb603c88814f24c3a7efd28105ecc3c5849d6a42b'}


def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as handle:
        while True:
            block=handle.read(65536)
            if not block:break
            h.update(block)
    return h.hexdigest()


def identity(pid):
    with open('/proc/'+str(pid)+'/stat') as handle:raw=handle.read(4096)
    end=raw.rindex(')');f=raw[end+2:].split()
    return {'pid':int(pid),'name':raw[raw.index('(')+1:end],
            'parent':int(f[1]),'starttime':f[19],
            'exe':os.readlink('/proc/'+str(pid)+'/exe')}


def stock_snapshot():
    rows=[]
    for pid in os.listdir('/proc'):
        if not pid.isdigit():continue
        try:
            row=identity(pid)
            if row['name'] in ('Z03','control_engine','weston','connmand','bluetoothd'):
                if row['name'] in ('Z03','control_engine'):row['parent_identity']=identity(row['parent'])
                rows.append(row)
        except (OSError,ValueError):pass
    return {'hashes':{p:digest(p) for p in PINS},'processes':sorted(rows,key=lambda r:r['pid'])}


def require_stock(snapshot):
    if snapshot['hashes']!=PINS:raise ValueError('Stock firmware differs from verified v2.4.0 baseline')
    for name in ('Z03','control_engine','weston'):
        rows=[r for r in snapshot['processes'] if r['name']==name]
        if len(rows)!=1:raise ValueError('Expected one stable stock '+name)
        if name in ('Z03','control_engine') and rows[0]['exe']!='/usr/bin/'+name:
            raise ValueError('A candidate process is already running')
    if os.path.lexists('/mnt/data/p011-menu'):raise ValueError('Existing temporary menu needs inspection')


def owned_directory(path,create=False):
    if path!=AREA and not path.startswith(AREA+'/'):raise ValueError('Outside toolbox directory')
    if os.path.normpath(path)!=path:raise ValueError('Noncanonical toolbox path')
    current=''
    for part in path.strip('/').split('/'):
        current+='/'+part
        if os.path.lexists(current):
            if os.path.islink(current) or not os.path.isdir(current):raise ValueError('Unsafe directory component')
        elif create and (current==AREA or current.startswith(AREA+'/')):os.mkdir(current,0o700)
        else:raise ValueError('Missing toolbox directory')
    if os.path.realpath(path)!=path:raise ValueError('Toolbox directory is redirected')
    return path


def verify_candidate(base):
    if not re.match(r'^'+AREA+r'/candidates/native-051-[0-9a-f]{16}$',base):
        raise ValueError('Unexpected candidate path')
    owned_directory(base)
    manifest=os.path.join(base,'SOURCE.sha256')
    if os.path.islink(manifest):raise ValueError('Linked manifest')
    with open(manifest,'rb') as handle:raw=handle.read(32769)
    if len(raw)>32768 or hashlib.sha256(raw).hexdigest()[:16]!=base.rsplit('-',1)[1]:
        raise ValueError('Candidate identity mismatch')
    expected={'SOURCE.sha256'}
    for line in raw.decode('ascii').splitlines():
        value,length,name=line.split(' ',2)
        if not re.match(r'^(runtime|device|web)/[A-Za-z0-9_.-]+$',name):raise ValueError('Unexpected candidate file')
        if name in expected:raise ValueError('Duplicate manifest entry')
        expected.add(name)
        path=os.path.join(base,name)
        owned_directory(os.path.dirname(path))
        if os.path.islink(path) or not os.path.isfile(path):raise ValueError('Missing or linked candidate file')
        if os.path.getsize(path)!=int(length) or digest(path)!=value:raise ValueError('Candidate file differs')
    observed=set()
    for directory,dirs,files in os.walk(base):
        for name in dirs:
            if os.path.islink(os.path.join(directory,name)):raise ValueError('Linked candidate directory')
        for name in files:observed.add(os.path.relpath(os.path.join(directory,name),base))
    if observed!=expected:raise ValueError('Unlisted candidate files')
    return hashlib.sha256(raw).hexdigest()
