"""Shared, bounded settings and resource policy; no account or network access."""
import json
import os
import stat


def quality_id(value):
    return type(value) is int and 0 <= value <= 65535


DEFAULTS = {'aspect':0,'dm_area':100,'dm_opacity':100,'dm_size':100,'dm_speed':100}
CHOICES = {'aspect':tuple(range(5)),'dm_area':(25,50,75,100),
           'dm_opacity':(25,50,75,100),'dm_size':(80,100,120,140),'dm_speed':(75,100,125,150)}


def settings(value):
    if not isinstance(value, dict):return dict(DEFAULTS)
    return {k:value.get(k) if type(value.get(k)) is int and value.get(k) in CHOICES[k] else v for k,v in DEFAULTS.items()}


class Preferences:
    """Our five numerical preferences only; never touches an account directory."""
    def __init__(self, directory):
        self.directory=directory
        try:os.mkdir(directory,0o700)
        except FileExistsError:pass
        info=os.lstat(directory)
        if not stat.S_ISDIR(info.st_mode) or os.path.islink(directory):raise ValueError('unsafe preferences directory')
        if os.name=='posix' and (info.st_uid!=os.getuid() or info.st_mode&0o077):raise ValueError('preferences directory permissions')
        self.path=os.path.join(directory,'settings-v1.json')
    def load(self):
        if not os.path.lexists(self.path):return settings({})
        info=os.lstat(self.path)
        if not stat.S_ISREG(info.st_mode) or info.st_size>4096:raise ValueError('unsafe preferences file')
        if os.name=='posix' and (info.st_uid!=os.getuid() or info.st_mode&0o077):raise ValueError('preferences file permissions')
        fd=os.open(self.path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
        with os.fdopen(fd,'r') as f:value=json.loads(f.read(4097))
        if not isinstance(value,dict) or type(value.get('schema')) is not int or value['schema']!=1:raise ValueError('unknown preferences schema')
        return settings(value.get('settings'))
    def save(self,value):
        self.load() # Refuse to overwrite an unknown/corrupt/user-owned file.
        path=os.path.join(self.directory,'.settings-'+os.urandom(8).hex()+'.tmp')
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        try:
            with os.fdopen(fd,'w') as f:json.dump({'schema':1,'settings':settings(value)},f);f.flush();os.fsync(f.fileno())
            os.replace(path,self.path)
        finally:
            if os.path.isfile(path):os.unlink(path)


def decode_budget(stream, available_kb=None):
    """Pre-allocation guard, not a 4K quality-ID cap or a speed promise.

    Budget 36 bytes/pixel for worst-case reference/thread/conversion buffers,
    plus 96 MiB headroom. The codec's independent 36 MP guard catches corrupt
    bitstream dimensions. Missing legacy durl geometry stays codec-guarded.
    """
    width,height=stream.get('width',0),stream.get('height',0)
    if type(width) is not int or type(height) is not int or min(width,height)<0:return False
    if width>16384 or height>16384 or width*height>36000000:return False
    if available_kb is None:
        try:
            with open('/proc/meminfo') as f:
                available_kb=next(int(line.split()[1]) for line in f if line.startswith('MemAvailable:'))
        except (OSError,ValueError,StopIteration):return width*height<=2073600
    return width*height*36+96*1024*1024 <= available_kb*1024
