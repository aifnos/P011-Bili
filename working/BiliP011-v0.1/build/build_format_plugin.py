"""Compose a private format observer without changing the production recipe."""
import hashlib
import pathlib
import build_cache_plugin
from format_omx_overlay import overlay


def build_plugin(work):
    work.mkdir(exist_ok=True)
    header = pathlib.Path('/src/probes/omx_format_bridge.h').read_bytes()
    (work / 'omx_format_bridge.h').write_bytes(header)
    original = build_cache_plugin.overlay

    def composed(name, source, fallback=False):
        if fallback:
            raise ValueError('Format observer is diagnostic only')
        return overlay(name, original(name, source, fallback=False))

    build_cache_plugin.overlay = composed
    try:
        plugin, modified, includes, libs = build_cache_plugin.build_plugin(work)
    finally:
        build_cache_plugin.overlay = original
    modified['omx_format_bridge.h'] = hashlib.sha256(header).hexdigest()
    return plugin, modified, includes, libs
