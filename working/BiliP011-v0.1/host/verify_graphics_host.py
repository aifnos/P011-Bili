"""Reproduce host guards and audit saved traces. Never invoke ADB or Docker."""
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

from wayland_evidence import analyze

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parents[1]
HISTORY = ('BiliP011-StripWindow-20260924-234732', 'BiliP011-StripWindow-20260924-234845',
           'BiliP011-StripWindow-20260925-002622','BiliP011-StripWindow-20260925-010301')
SOURCES = ('host/wayland_evidence.py', 'host/test_wayland_evidence.py',
           'host/test_graphics_investigation.py', 'host/verify_graphics_host.py',
           'host/window_buffer_probe.py', 'build/build_window_probe.py',
           'probes/window_buffer_probe.cpp', 'client/drm_trace.hpp',
           'host/private_sdl_artifact.py','host/test_private_sdl_artifact.py',
           'build/build_sdl_probe.py','build/build_strip_player.py','build/build_client.py',
           'build/export_runtime.py','build/Dockerfile','host/strip_player_artifact.py',
           'host/test_strip_player_artifact.py','client/player_surface.hpp',
           'host/test_display_first.py','client/player_v2.cpp',
           'host/player_surface_test.cpp','host/client_results.py',
           'host/test_client_results.py','host/review_gallery.py',
           'third_party/SDL2-2.0.8-p011/src/video/wayland/SDL_waylandwindow.c',
           'third_party/SDL2-2.0.8-p011/src/video/wayland/SDL_waylandwindow.h',
           'third_party/SDL2-2.0.8-p011/src/video/wayland/SDL_waylandsym.h',
           'third_party/SDL2-2.0.8-p011/P011-CHANGES.md',
           'third_party/SDL2-2.0.8-p011/COPYING.txt')


def main():
    out = ROOT/'logs'/('BiliP011-GraphicsHost-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    out.mkdir()
    command = [sys.executable, '-m', 'unittest', 'test_graphics_investigation',
               'test_wayland_evidence', 'test_private_sdl_artifact',
               'test_strip_player_artifact','test_client_results','test_display_first','-v']
    report = {'schema':1, 'device_accessed':False, 'docker_started':False,
              'physical_acceptance':False, 'new_binary_built':False,
              'source_sha256':{name:hashlib.sha256((BASE/name).read_bytes()).hexdigest() for name in SOURCES},
              'historical_trace_audits':[]}
    try:
        result = subprocess.run(command,cwd=BASE/'host',stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45)
        stdout,stderr=result.stdout,result.stderr
        report['host_test_exit']=result.returncode
        report['host_test_timeout']=False
    except subprocess.TimeoutExpired as error:
        stdout,stderr=error.stdout or b'',error.stderr or b''
        report['host_test_exit']=None
        report['host_test_timeout']=True
    (out/'tests.stdout.raw').write_bytes(stdout)
    (out/'tests.stderr.raw').write_bytes(stderr)
    for name in HISTORY:
        trace = ROOT/'logs'/name/'probe.stderr.raw'
        if not trace.is_file():
            report['historical_trace_audits'].append({'source':name,'available':False})
            continue
        raw = trace.read_bytes()
        report['historical_trace_audits'].append({'source':name,'available':True,
            'trace_sha256':hashlib.sha256(raw).hexdigest(),
            'new_candidate_evidence':False,
            'excluded_old_binary_rerun':name.endswith('234845'),
            'audit':analyze(raw.decode('utf-8',errors='replace'))})
    # Passing this host check is deliberately independent of historical GPU
    # failures; it never upgrades them, nor proves new device readiness.
    report['host_checks_passed'] = report['host_test_exit']==0 and not report['host_test_timeout']
    (out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    target=out.with_name(out.name+'-safe.zip')
    with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED) as bundle:
        for name in ('result.json','tests.stdout.raw','tests.stderr.raw'):
            bundle.write(out/name,name)
        for name in SOURCES:
            bundle.write(BASE/name,'source/'+name)
    with zipfile.ZipFile(target) as bundle:
        if bundle.testzip() is not None:
            raise ValueError('ZIP CRC failed')
        if 'probe.stderr.raw' in '\n'.join(bundle.namelist()):
            raise ValueError('Private protocol trace included')
    print('HOST_CHECKS_PASSED='+str(report['host_checks_passed']))
    print('LOG_DIR='+str(out))
    print('RESULT_ZIP='+str(target))
    print('ZIP_SHA256='+hashlib.sha256(target.read_bytes()).hexdigest())
    return 0 if report['host_checks_passed'] else 1


if __name__=='__main__':raise SystemExit(main())
