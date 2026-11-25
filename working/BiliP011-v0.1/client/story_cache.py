"""One priority worker: next opening segment, then the following one.

Python 3.5. Four entries (previous/current/next/next+1), at most 4.5 MiB each
for the prefix path, 90 s URL validity. No second decoder. Yield immediately
to playback starvation/switching; completed prefixes survive cancellation.
"""
import os
import re
import stat
import threading
import time
from collections import OrderedDict


def identity(args):
    return tuple(args.get(k, '') for k in ('kind', 'bvid', 'cid', 'ep', 'quality', 'codec'))


def can_prefetch(state,metadata=False):
    # Older frozen players lack this capability field and only accept HTTPS.
    return (type(state.get('video_seek_actions')) is int and state.get('active') is True
            and not state.get('switch_pending') and state.get('position',0)>=(.15 if metadata else 2)
            and (metadata or not state.get('prefix_cache_capable') or
                 state.get('prefetch_safe') is True and not state.get('performance_limited')))


class PlaybackPriority:
    """Cancellation view sampled by the native helper every 200 ms."""
    def __init__(self,cancel,ready):self.cancel=cancel;self.ready=ready;self.yielded=False
    def is_set(self):
        if self.cancel.is_set():return True
        if not self.ready():self.yielded=True
        return self.yielded


def purge(root):
    """Guardian calls only after every exact-session child has stopped."""
    directory=os.path.join(root,'preload')
    if not os.path.lexists(directory):return 0
    if os.path.islink(directory) or not stat.S_ISDIR(os.lstat(directory).st_mode):raise ValueError('cache directory')
    names=os.listdir(directory)
    if len(names)>24:raise ValueError('cache file bound')
    for name in names:
        path=os.path.join(directory,name)
        if not re.match(r'^[a-f0-9]{16}-[va]\.(?:m4s|head)(?:\.part)?$',name) or os.path.islink(path) or not stat.S_ISREG(os.lstat(path).st_mode):raise ValueError('cache file identity')
    for name in names:os.unlink(os.path.join(directory,name))
    return len(names)


class StoryCache:
    def __init__(self, root, resolve, download, ready, clock=time.monotonic, metadata_ready=None,relay=None):
        self.directory=os.path.join(root, 'preload')
        if not os.path.exists(self.directory):os.mkdir(self.directory, 0o700)
        info=os.lstat(self.directory)
        if not stat.S_ISDIR(info.st_mode) or os.path.islink(self.directory):raise ValueError('cache directory')
        os.chmod(self.directory, 0o700)
        self.resolve,self.download,self.ready,self.clock=resolve,download,ready,clock
        self.metadata_ready=metadata_ready or ready
        self.relay=relay
        self.lock=threading.Condition();self.closed=False;self.pending=None;self.version=0
        self.cancel=threading.Event();self.rows=OrderedDict();self.files=set()
        self.stats=dict(requests=0,resolved=0,completed=0,metadata_hits=0,media_hits=0,misses=0,canceled=0,failed=0,bytes=0,yields=0,reused=0)
        self.thread=threading.Thread(target=self.run);self.thread.daemon=True;self.thread.start()

    def schedule(self, args):
        with self.lock:
            if self.closed:return
            key=identity(args)
            if key in self.rows and self.clock()-self.rows[key]['at']<90:return
            self.version+=1;self.cancel.set();self.cancel=threading.Event()
            self.pending=(self.version,dict(args),self.cancel);self.stats['requests']+=1;self.lock.notify_all()

    def schedule_provider(self,provider):
        with self.lock:
            if self.closed:return
            self.version+=1;self.cancel.set();self.cancel=threading.Event()
            self.pending=(self.version,provider,self.cancel);self.stats['requests']+=1;self.lock.notify_all()

    def cancel_pending(self):
        with self.lock:self.cancel.set();self.pending=None

    def take(self, args):
        with self.lock:
            row=self.rows.get(identity(args))
            if row and self.clock()-row['at']<90:
                # Pin the selected entry as newest before the following
                # look-ahead can evict old history. Do not renew its TTL.
                self.rows.move_to_end(identity(args))
                result=dict(row['data']);cached=row.get('cached',False)
                if cached:
                    if self.relay:result.update(row['urls'])
                    else:
                        for field in ('video','audio'):
                            if result.get(field):result[field]='file://'+os.path.join(self.directory,row['file']+('-v.m4s' if field=='video' else '-a.m4s'))
                self.stats['media_hits' if cached else 'metadata_hits']+=1
                return dict(row['args']),result
            self.stats['misses']+=1
            return None

    def remove(self, key):
        if not re.match(r'^[a-f0-9]{16}$',key):return
        if self.relay:self.relay.remove(key)
        for suffix in ('-v.m4s','-a.m4s','-v.m4s.part','-a.m4s.part','-v.head','-a.head','-v.head.part','-a.head.part'):
            path=os.path.join(self.directory,key+suffix)
            try:
                info=os.lstat(path)
                if stat.S_ISREG(info.st_mode) and not os.path.islink(path):os.unlink(path)
            except OSError:pass
        self.files.discard(key)

    def run(self):
        while True:
            with self.lock:
                while self.pending is None and not self.closed:self.lock.wait(.5)
                if self.closed:break
                version,args,cancel=self.pending;self.pending=None
            try:
                # Allow the currently selected item to reach stable playback.
                while not cancel.is_set() and not self.metadata_ready():cancel.wait(.1)
                if cancel.is_set():continue
                if callable(args):args=args(cancel)
                if cancel.is_set():continue
                for requested in (args[:2] if isinstance(args,list) else [args]):
                    if cancel.is_set():break
                    try:self.prepare(requested,cancel)
                    except Exception:
                        with self.lock:self.stats['failed']+=not cancel.is_set()
            except Exception:
                with self.lock:self.stats['failed']+=1
        with self.lock:
            for key in list(self.files):self.remove(key)
            self.rows.clear()

    def prepare(self,args,cancel):
        key=identity(args)
        with self.lock:
            row=self.rows.get(key)
            if row and self.clock()-row['at']>=90:row=None
            if row and row['cached']:self.stats['reused']+=1;return
        if row is None:
            resolved,data=self.resolve(args,cancel)
            with self.lock:
                if self.closed or cancel.is_set():return
                old=self.rows.pop(key,None)
                if old and old.get('file'):self.remove(old['file'])
                row=dict(args=resolved,data=data,at=self.clock(),cached=False)
                self.rows[key]=row;self.stats['resolved']+=1
                while len(self.rows)>4:
                    _,old=self.rows.popitem(last=False)
                    if old.get('file'):self.remove(old['file'])
        # A canceled attempt is retried only once playback has real headroom.
        # The 90 s metadata TTL bounds starvation/retry without an infinite loop.
        while not cancel.is_set() and self.clock()-row['at']<90:
            while not cancel.is_set() and not self.ready():cancel.wait(.1)
            if cancel.is_set():return
            file_key=os.urandom(8).hex();priority=PlaybackPriority(cancel,self.ready)
            with self.lock:self.files.add(file_key)
            try:
                data=row['data']
                value=self.download(dict(video=data['video'],audio=data.get('audio',''),key=file_key),priority)
                with self.lock:
                    if not self.closed and not cancel.is_set() and not priority.yielded and value.get('cached') is True:
                        urls=self.relay.register(file_key,data,value) if self.relay else {}
                        row.update(cached=True,file=file_key,urls=urls);file_key=None
                        self.stats['completed']+=1;self.stats['bytes']+=int(value.get('bytes',0))
                        return
                if not priority.yielded:return
            except Exception:
                if not priority.yielded and not cancel.is_set():raise
            finally:
                with self.lock:
                    if file_key:self.remove(file_key)
                    if priority.yielded:self.stats['yields']+=1
                    if cancel.is_set():self.stats['canceled']+=1

    def close(self):
        with self.lock:self.closed=True;self.cancel.set();self.lock.notify_all()
        self.thread.join(3)
        with self.lock:return dict(self.stats,worker_stopped=not self.thread.is_alive())
