"""One-click host-only diagnostic regression and bounded local evidence ZIP."""
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

BASE=Path(__file__).resolve().parents[1]
ROOT=BASE.parents[1]
TESTS=('test_cached_compat','test_cached_worker','test_cached_worker_audit',
       'test_vsp_wait_observer','test_worker_wait_audit','test_omx_format_profile',
       'test_performance_trial','test_dm_delay_probe','test_kernel_observability','test_ddr_observation','test_vsp_readback','test_screen_rate_trial',
       'test_presentation_evidence')
SOURCES=('client/frame_telemetry.hpp','host/player_controls_test.cpp','build/build_strip_player.py',
         'client/h264_access_unit.hpp','client/hardware_worker.cpp','client/hardware_client.hpp',
         'client/player_v2.cpp','client/service.py','client/dm_delay_probe.py','client/BiliPerformance.qml',
         'probes/hardware_seek_probe.cpp',
         'probes/cached_compat_guard.hpp','probes/omx_format_bridge.h',
         'probes/omx_format_stats.hpp','probes/vsp_wait_observer.cpp',
         'probes/vsp_gap_stats.hpp','probes/vsp_cycle_stats.hpp',
         'build/cached_compat_overlay.py','build/format_omx_overlay.py',
         'build/build_cached_worker.py','build/build_format_plugin.py',
         'host/cached_compat_evidence.py','host/cached_seek_trial.py',
         'host/cached_worker_artifact.py','host/cached_worker_audit.py',
         'host/worker_wait_audit.py','host/omx_format_profile.py',
         'host/cached_compat_guard_test.cpp','host/vsp_wait_mock.cpp',
         'host/h264_access_unit_test.cpp','host/performance_trial.py','host/build_awake_trial.py',
         'host/kernel_observability_audit.py','host/inspect_kernel_graphics.py',
         'host/ddr_observation.py','host/vsp_readback.py','host/screen_rate_trial.py',
         'client/wayland_presentation.hpp','host/presentation_evidence.py','build/presentation_protocol.py','third_party/presentation-time-v1.xml',
         'host/verify_performance_host.py','VERIFY_BILI_PERFORMANCE_HOST.cmd')


def main():
    out=ROOT/'logs'/('BiliP011-PerformanceHost-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    out.mkdir()
    files=tuple(SOURCES)+tuple('host/'+name+'.py' for name in TESTS)
    report=dict(schema=1,device_accessed=False,docker_started=False,new_binary_built=False,
                playback_passed=False,full_source_rate_passed=False,physical_acceptance=False,
                source_sha256={name:hashlib.sha256((BASE/name).read_bytes()).hexdigest() for name in files})
    try:
        result=subprocess.run([sys.executable,'-m','unittest',*TESTS,'-v'],cwd=BASE/'host',
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45)
        stdout,stderr=result.stdout,result.stderr
        report.update(host_test_exit=result.returncode,host_test_timeout=False)
    except subprocess.TimeoutExpired as error:
        stdout,stderr=error.stdout or b'',error.stderr or b''
        report.update(host_test_exit=None,host_test_timeout=True)
    report['host_checks_passed']=report['host_test_exit']==0 and not report['host_test_timeout']
    bodies={'result.json':json.dumps(report,indent=2).encode('ascii'),
            'tests.stdout.raw':stdout,'tests.stderr.raw':stderr}
    for name,body in bodies.items():(out/name).write_bytes(body)
    archive=out.with_name(out.name+'-safe.zip')
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for name,body in bodies.items():z.writestr(name,body)
        z.writestr('SHA256.json',json.dumps({n:hashlib.sha256(b).hexdigest() for n,b in bodies.items()},indent=2))
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:raise ValueError('Host evidence CRC failed')
        hashes=json.loads(z.read('SHA256.json'))
        if any(hashlib.sha256(z.read(n)).hexdigest()!=h for n,h in hashes.items()):raise ValueError('Host evidence hash failed')
    print('HOST_CHECKS_PASSED='+str(report['host_checks_passed']))
    print('RESULT_ZIP='+str(archive))
    print('ZIP_SHA256='+hashlib.sha256(archive.read_bytes()).hexdigest())
    return 0 if report['host_checks_passed'] else 1


if __name__=='__main__':raise SystemExit(main())
