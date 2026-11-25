"""Private local history, not Bilibili account writes. Python 3.5 compatible.

Only normalized identifiers, display text and positions; never URLs/cookies.
Automation uses its isolated trial directory. Unknown files are not replaced.
"""
import json
import math
import os
import re
import stat
import threading
import time


def text(value, limit):
    return ''.join(c for c in value if ord(c) >= 32)[:limit] if isinstance(value,str) else ''


def item(value):
    if not isinstance(value,dict):raise ValueError('history item')
    result={'kind':value.get('kind','video')}
    if result['kind'] not in ('video','episode'):raise ValueError('history kind')
    for key in ('bvid','cid','ep','aid'):
        v=value.get(key,'')
        if not isinstance(v,str) or (v and not re.match((r'BV[0-9A-Za-z]{10}' if key=='bvid' else r'[0-9]{1,20}')+'$',v)):raise ValueError('history identifier')
        result[key]=v
    if result['kind']=='video' and not (result['bvid'] and result['cid']):raise ValueError('history video')
    if result['kind']=='episode' and not result['ep']:raise ValueError('history episode')
    for key in ('title','part_title','up'):result[key]=text(value.get(key),100)
    for key in ('position','duration','updated'):
        v=value.get(key,0)
        if type(v) not in (int,float) or not math.isfinite(v) or v<0 or v>10000000000:raise ValueError('history number')
        result[key]=v
    return result


def identity(row):return (row.get('kind','video'),row.get('bvid',''),row.get('cid',''),row.get('ep',''))


class Library:
    def __init__(self,directory):
        self.directory=directory;self.lock=threading.RLock()
        try:os.mkdir(directory,0o700)
        except FileExistsError:pass
        info=os.lstat(directory)
        if not stat.S_ISDIR(info.st_mode) or os.path.islink(directory):raise ValueError('library directory')
        if os.name=='posix' and (info.st_uid!=os.getuid() or info.st_mode&0o077):raise ValueError('library permissions')
        self.path=os.path.join(directory,'library-v1.json')
        self.load()

    def load(self):
        with self.lock:
            if not os.path.lexists(self.path):return {'history':[],'searches':[]}
            info=os.lstat(self.path)
            if not stat.S_ISREG(info.st_mode) or info.st_size>131072 or info.st_nlink!=1:raise ValueError('library file')
            if os.name=='posix' and (info.st_uid!=os.getuid() or info.st_mode&0o077):raise ValueError('library permissions')
            fd=os.open(self.path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
            with os.fdopen(fd,'r',encoding='utf-8') as f:value=json.loads(f.read(131073))
            if not isinstance(value,dict) or type(value.get('schema')) is not int or value['schema']!=1:raise ValueError('library schema')
            history=value.get('history');searches=value.get('searches')
            if not isinstance(history,list) or len(history)>60 or not isinstance(searches,list) or len(searches)>20:raise ValueError('library bounds')
            if any(not isinstance(s,str) or not s or len(s.encode('utf-8'))>160 for s in searches):raise ValueError('search history')
            return {'history':[item(v) for v in history],'searches':searches}

    def save(self,value):
        # Callers hold the RLock across read/modify/write.
        self.load()
        # bytes.hex is supported by the pen's Python 3.5.
        path=os.path.join(self.directory,'.library-'+os.urandom(8).hex()+'.tmp')
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(dict(value,schema=1),f,ensure_ascii=True);f.flush();os.fsync(f.fileno())
            os.replace(path,self.path)
        finally:
            if os.path.isfile(path):os.unlink(path)

    def search(self,term):
        if not isinstance(term,str) or not term.strip() or len(term.encode('utf-8'))>160:raise ValueError('search')
        term=text(term.strip(),160)
        if not term:return
        with self.lock:
            value=self.load();value['searches']=([term]+[s for s in value['searches'] if s!=term])[:20];self.save(value)

    def record(self,metadata,position,duration):
        row=item(dict(metadata,position=position,duration=duration,updated=time.time()))
        if position<2 or duration<=0:return
        with self.lock:
            value=self.load();value['history']=([row]+[v for v in value['history'] if identity(v)!=identity(row)])[:60];self.save(value)

    def resume(self,metadata):
        with self.lock:
            for row in self.load()['history']:
                if identity(row)==identity(metadata):
                    return row['position'] if 3<=row['position']<row['duration']-5 else 0
        return 0

    def clear(self,section):
        if section not in ('history','searches'):raise ValueError('library section')
        with self.lock:
            value=self.load();value[section]=[];self.save(value)
