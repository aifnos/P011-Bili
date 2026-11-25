"""Pure export gate for the content-only player and its private SDL pair."""
import hashlib
import json
from private_sdl_artifact import validate_private_artifact


def source_hashes(base):
    names=[p.relative_to(base).as_posix() for p in (base/'client').rglob('*')
           if p.is_file() and p.suffix in ('.cpp','.hpp')]
    names+=['host/media_range_test.cpp','build/build_client.py','build/build_strip_player.py','build/build_hardware.py',
            'build/presentation_protocol.py','third_party/presentation-time-v1.xml',
            'build/export_runtime.py','host/strip_player_artifact.py',
            'build/test_cache_vendor_gate.py','host/hardware_cache_gate_test.cpp','build/test_cached_client.py','host/hardware_cache_close_test.cpp',
            'host/player_geometry_test.cpp','host/player_surface_test.cpp','host/player_controls_test.cpp','host/player_phase_test.cpp','host/player_packets_test.cpp','host/player_features_test.cpp','host/danmaku_timeline_test.cpp','host/hardware_clock_test.cpp','host/h264_access_unit_test.cpp']
    return {name:hashlib.sha256((base/name).read_bytes()).hexdigest() for name in sorted(names)}


def validate_strip_player(base):
    _,_,runtime,runtime_sha,_=validate_private_artifact(base)
    meta=json.loads((base/'out/strip-player.build.json').read_text(encoding='utf-8'))
    if meta.get('schema')!=1 or meta.get('sources')!=source_hashes(base):
        raise ValueError('Strip player source differs from successful build')
    if meta.get('sdl_sha256')!=runtime_sha:raise ValueError('Strip player SDL pair differs')
    for name in ('bili-player','bili-api','bili-hw'):
        path=base/'out'/name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=meta.get('binaries',{}).get(name):
            raise ValueError('Strip player binary differs: '+name)
    if meta.get('bundled_omx'):validate_bundled_omx(base,meta)
    return runtime


def validate_bundled_omx(base,meta=None):
    if meta is None:meta=json.loads((base/'out/strip-player.build.json').read_text(encoding='utf-8'))
    spec=meta.get('bundled_omx')
    if not isinstance(spec,dict):raise ValueError('Player not built for private OMX')
    if spec.get('output_cache') is True:
        from output_cache_artifact import validate
    else:
        from private_omx_artifact import validate
    binary,plugin=validate(base,base/'out'/spec.get('artifact',''))
    if plugin['copy_mode'] not in (2,3,4) or plugin['sha256']!=spec.get('sha256'):raise ValueError('Bundled OMX pair differs')
    if (plugin['copy_mode']==4)!=(spec.get('fused_copy') is True):raise ValueError('Bundled fused-copy capability differs')
    return binary
