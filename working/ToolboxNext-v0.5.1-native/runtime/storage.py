"""Confined user files. Linux uses directory handles and O_NOFOLLOW throughout."""
import os
import re
import stat
import time
import threading
import urllib.parse

AUDIO = ('.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac', '.opus')
VIDEO = ('.mp4', '.mkv', '.webm', '.avi', '.mov', '.m4v')
IMAGE = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp')
TEXT = ('.txt', '.md', '.log', '.csv')
RESOURCE = ('.nes', '.gb', '.gbc', '.gba', '.rom', '.zip', '.bin', '.dat', '.sav', '.json')
FOLDERS = ('Music', 'Pictures', 'Text', 'GameResources', 'Screenshots', 'Exports')
MAX_FILE = 64 * 1024 * 1024

def native_name(value):
    # Vendor Python 3.5 starts with ASCII filesystem encoding and has no UTF-8
    # locale installed. Linux filenames are bytes; encode our validated UTF-8
    # names explicitly instead of changing global locale or replacing files.
    return value.encode('utf-8') if os.name=='posix' and isinstance(value,str) else value


def kind(name):
    ext = os.path.splitext(name)[1].lower()
    return 'audio' if ext in AUDIO else 'video' if ext in VIDEO else 'image' if ext in IMAGE else 'text' if ext in TEXT else 'resource'


def components(path):
    if not isinstance(path, str) or len(path) > 1024 or '\\' in path or ':' in path or any(ord(c) < 32 for c in path):
        raise ValueError('无效路径')
    if not path:
        return []
    parts = path.split('/')
    if any(p in ('', '.', '..') or p.startswith('.') or len(p.encode('utf-8')) > 240 for p in parts):
        raise ValueError('禁止隐藏或越界路径')
    if parts[0] not in FOLDERS:
        raise ValueError('目录不在用户白名单')
    return parts


class FileStore:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        if os.path.realpath(self.root) != self.root:
            raise ValueError('用户目录不能经过符号链接')
        os.makedirs(self.root, mode=0o700, exist_ok=True)
        self.lock = threading.RLock()
        self.fd_mode = os.open in os.supports_dir_fd and hasattr(os, 'O_NOFOLLOW')
        self.rootfd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW) if self.fd_mode else None
        for name in FOLDERS:
            p = os.path.join(self.root, name)
            if os.path.lexists(p) and (os.path.islink(p) or not os.path.isdir(p)):
                raise ValueError('用户子目录不是普通目录')
            os.makedirs(p, mode=0o700, exist_ok=True)

    def close(self):
        if self.rootfd is not None:
            os.close(self.rootfd)
            self.rootfd = None

    def directory(self, parts):
        if self.fd_mode:
            fd = os.dup(self.rootfd)
            try:
                for part in parts:
                    nxt = os.open(native_name(part), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    os.close(fd)
                    fd = nxt
                return fd
            except Exception:
                os.close(fd)
                raise
        # Host preview fallback. Target Linux takes the descriptor-based branch.
        path = self.root
        for part in parts:
            path = os.path.join(path, part)
            if os.path.islink(path) or not os.path.isdir(path):
                raise ValueError('目录不可用')
        if os.path.realpath(path) != path:
            raise ValueError('禁止链接')
        return path

    def release(self, parent):
        if self.fd_mode:
            os.close(parent)

    def info(self, parent, name):
        return os.stat(native_name(name), dir_fd=parent, follow_symlinks=False) if self.fd_mode else os.lstat(native_name(os.path.join(parent, name)))

    def listing(self, path='', offset=0):
        parts = components(path)
        if not 0 <= offset <= 100000:
            raise ValueError('分页范围无效')
        parent = self.directory(parts)
        try:
            # Bound enumeration as well as rendering; never recursively walk.
            names = []
            it = os.scandir(native_name(parent if not self.fd_mode else '/proc/self/fd/' + str(parent)))
            try:
                for entry in it:
                    if len(names) >= 2000:
                        break
                    try:name=entry.name.decode('utf-8') if isinstance(entry.name,bytes) else entry.name
                    except UnicodeDecodeError:continue
                    if not name.startswith('.'):
                        names.append(name)
            finally:
                if hasattr(it, 'close'): it.close()
            rows = []
            for name in sorted(names, key=lambda n:n.lower()):
                rel = '/'.join(parts + [name])
                try:
                    components(rel)
                    st = self.info(parent, name)
                    if not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
                        continue
                    rows.append({'name':name, 'path':rel, 'kind':'directory' if stat.S_ISDIR(st.st_mode) else kind(name),
                                 'bytes':st.st_size, 'modified':int(st.st_mtime)})
                except (OSError, ValueError):
                    continue
            rows.sort(key=lambda r:(r['kind'] != 'directory', r['name'].lower()))
            return {'path':path, 'entries':rows[offset:offset+100], 'offset':offset,
                    'next':offset+100 if len(rows) > offset+100 else None, 'limited':len(names) >= 2000}
        finally:
            self.release(parent)

    def open_file(self, path):
        parts = components(path)
        if len(parts) < 2:
            raise ValueError('请选择用户文件')
        parent = self.directory(parts[:-1])
        try:
            flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
            if not self.fd_mode and os.path.islink(os.path.join(parent, parts[-1])):
                raise ValueError('禁止链接')
            fd = os.open(native_name(parts[-1]), flags, dir_fd=parent) if self.fd_mode else os.open(native_name(os.path.join(parent, parts[-1])), flags)
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                os.close(fd)
                raise ValueError('不是普通文件')
            return os.fdopen(fd, 'rb'), st
        finally:
            self.release(parent)

    def text(self, path):
        if kind(path) != 'text':
            raise ValueError('只预览纯文本')
        handle, st = self.open_file(path)
        with handle:
            data = handle.read(65536)
        return {'text':data.decode('utf-8-sig', 'replace'), 'truncated':st.st_size > len(data), 'encoding':'UTF-8'}

    def write_new(self, path, stream, length):
        parts = components(path)
        if len(parts) < 2 or os.path.splitext(parts[-1])[1].lower() not in AUDIO+VIDEO+IMAGE+TEXT+RESOURCE:
            raise ValueError('不支持的文件类型')
        if not 0 < length <= MAX_FILE:
            raise ValueError('单文件上限 64 MiB，不接收空文件')
        with self.lock:
            parent = self.directory(parts[:-1])
            temp = '.upload-' + os.urandom(12).hex()
            created = False
            try:
                if hasattr(os, 'statvfs'):
                    fs = os.fstatvfs(parent) if self.fd_mode else os.statvfs(parent)
                    if fs.f_bavail * fs.f_frsize < length + 32*1024*1024:
                        raise ValueError('存储空间不足，需保留 32 MiB')
                try:
                    self.info(parent, parts[-1])
                except FileNotFoundError:
                    pass
                else:
                    raise FileExistsError('同名文件已存在，请重命名后上传')
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
                fd = os.open(temp, flags, 0o600, dir_fd=parent) if self.fd_mode else os.open(os.path.join(parent,temp), flags, 0o600)
                created = True
                with os.fdopen(fd, 'wb') as target:
                    remaining = length
                    while remaining:
                        chunk = stream.read(min(65536, remaining))
                        if not chunk:
                            raise ValueError('上传中断')
                        target.write(chunk)
                        remaining -= len(chunk)
                    target.flush()
                    os.fsync(target.fileno())
                # Atomic no-clobber publication. Existing files are never overwritten.
                if self.fd_mode:
                    os.link(temp, native_name(parts[-1]), src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                else:
                    os.link(os.path.join(parent,temp), os.path.join(parent,parts[-1]))
                return {'path':path, 'bytes':length}
            finally:
                if created:
                    if self.fd_mode:
                        os.unlink(temp, dir_fd=parent)
                    else:
                        os.unlink(os.path.join(parent,temp))
                self.release(parent)
