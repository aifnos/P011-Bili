"""Pure host/container artifact identity; no process, device or network calls."""
import hashlib
import json

INPUT_NAMES = ('probes/window_buffer_probe.cpp','client/drm_trace.hpp',
               'build/build_sdl_probe.py','host/private_sdl_artifact.py')


def tree_hash(root):
    if not (root/'src/video/wayland/SDL_waylandwindow.c').is_file():
        raise ValueError('Missing private SDL source tree')
    digest=hashlib.sha256()
    # A fixed POSIX string key makes Windows and Linux use the same order.
    for path in sorted(root.rglob('*'),key=lambda p:p.relative_to(root).as_posix()):
        if path.is_symlink():raise ValueError('Linked SDL source')
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode()+b'\0')
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def validate_private_artifact(base):
    out=base/'out/private-sdl-probe'
    meta=json.loads((out/'build.json').read_text(encoding='utf-8'))
    if meta.get('schema')!=2 or set(meta.get('sources',{}))!=set(INPUT_NAMES):
        raise ValueError('Unknown private SDL manifest')
    for name,expected in meta['sources'].items():
        if hashlib.sha256((base/name).read_bytes()).hexdigest()!=expected:
            raise ValueError('Private SDL probe source changed: '+name)
    if tree_hash(base/'third_party/SDL2-2.0.8-p011')!=meta.get('sdl_tree_sha256'):
        raise ValueError('Private SDL library source changed')
    if meta.get('configure_timeout_ms')!=500:raise ValueError('Unexpected configure bound')
    for name,key in (('window-buffer-probe','binary_sha256'),('libSDL2-2.0.so.0','runtime_sha256')):
        path=out/name
        if path.is_symlink():raise ValueError('Linked artifact')
        raw=path.read_bytes()
        if (hashlib.sha256(raw).hexdigest()!=meta.get(key) or raw[:6]!=b'\x7fELF\x01\x01'
                or raw[18:20]!=b'\x28\x00'):
            raise ValueError('Changed or non-ARM32 private artifact')
    identity=hashlib.sha256((meta['binary_sha256']+meta['runtime_sha256']).encode('ascii')).hexdigest()
    return out/'window-buffer-probe',meta['binary_sha256'],out/'libSDL2-2.0.so.0',meta['runtime_sha256'],identity
