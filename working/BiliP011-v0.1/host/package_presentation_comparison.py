"""PC-only, immutable packaging of this fixed presentation/readback experiment.

Only pinned privacy-filtered child archives, diagnostic sources and selected
restoration fields are included. Factory binaries and raw factory logs stay local.
"""
import datetime
import hashlib
import io
import json
from pathlib import Path
import zipfile

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parents[1]
LOGS = ROOT / 'logs'
CHILDREN = {
    'BiliP011-PerformanceTrial-20260925-153158-safe.zip': '04a3e64a334fac1c6eab201883e30e5f1ce99a397c5a92e632e27fcfb2c1808e',
    'BiliP011-PerformanceTrial-20260925-153445-safe.zip': 'a70e10e1ce3997f81373528016e0e7fc4776bd5d00cdc4d635e98c7cebd19f49',
    'BiliP011-WorkerWait-Audit-20260925-154604.zip': '9af3de10537a4224f5848f83b50c0edf0cfc39b3969ac3c0455310267adf2462',
    'BiliP011-WorkerWait-Audit-20260925-153528.zip': '8db3e10b201cc44d1e14cbf05fd0aa685a17f09fedabf7ba582b9b8fbb027be3',
    'BiliP011-PerformanceHost-20260925-154605-819729-safe.zip': '53806d89f307dc1812d9ad621de9ece7b2c0a9ce4844cbcfe920b02eaf903b4b',
}
SOURCES = (
    'client/wayland_presentation.hpp', 'client/player_v2.cpp',
    'third_party/presentation-time-v1.xml', 'build/presentation_protocol.py',
    'build/build_client.py', 'build/build_strip_player.py',
    'host/strip_player_artifact.py', 'host/test_strip_player_artifact.py',
    'host/presentation_evidence.py', 'host/test_presentation_evidence.py',
    'host/performance_trial.py', 'host/client_results.py',
    'probes/vsp_wait_observer.cpp', 'host/vsp_wait_mock.cpp',
    'host/vsp_readback.py', 'host/test_vsp_readback.py',
    'host/cached_seek_trial.py', 'host/worker_wait_audit.py',
    'host/test_worker_wait_audit.py', 'host/verify_performance_host.py',
    'host/package_presentation_comparison.py', 'TEST_BILI_PRESENTATION.cmd',
)
STOCK_HASHES = {
    '/usr/bin/Z03': 'cb8d6a78617d50f64c6adc8056427dd963bc83979cbb04e349275dd8e8ffb62a',
    '/usr/bin/control_engine': '364b0bf820799070e89d9362000de4a3796a0e6a2d5f4d657464c6385b8dbd6d',
    '/usr/bin/zyb_z03_launch.sh': '7bce5379e3cc78e5bd8c04ceb603c88814f24c3a7efd28105ecc3c5849d6a42b',
}


def bounded(path, limit=1024*1024):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError('Unexpected evidence file')
    return path.read_bytes()


def read(name):
    return json.loads(bounded(LOGS / name / 'result.json'))


def encode(value):
    return json.dumps(value, ensure_ascii=True, indent=2).encode('ascii')


def verify_child(body, digest):
    if hashlib.sha256(body).hexdigest() != digest:
        raise ValueError('Frozen safe evidence changed')
    with zipfile.ZipFile(io.BytesIO(body)) as child:
        if child.testzip() is not None:
            raise ValueError('Child evidence CRC differs')


def main():
    report = ROOT / '04_Documents/P011-Bili呈现上限与VSP档位读回-20260925.md'
    files = {'REPORT.md': bounded(report)}
    for name, digest in CHILDREN.items():
        body = bounded(LOGS / name, 25*1024*1024)
        verify_child(body, digest)
        files['evidence/' + name] = body
    for name in SOURCES:
        files['diagnostic-sources/' + name] = bounded(BASE / name)

    # Independently validate the observation while preserving the old full-rate
    # verdict. Never infer a performance pass from a successful finite trial.
    from presentation_evidence import analyze
    player_summaries = []
    for stamp in ('153158', '153445'):
        name = 'BiliP011-PerformanceTrial-20260925-' + stamp
        result = read(name)
        observed = analyze(json.loads(bounded(LOGS / name / 'device/presentation-feedback.json', 8*1024*1024)))
        if not observed['evidence_complete'] or any(result['presentation'].get(k) != v for k, v in observed.items()):
            raise ValueError('Presentation summary differs from original rows')
        if result['recovery_passed'] is not True or result['presentation'].get('backlight_on_during_sampled_playback') is not True:
            raise ValueError('Incomplete device recovery or lit-display evidence')
        if result['smoothness_passed'] is not (stamp == '153158'):
            raise ValueError('Historical source-rate verdict changed')
        # Source streams and their account/URL responses are deliberately absent.
        player_summaries.append({
            'run': name, 'source_fps': result['metrics']['playing']['source_fps'],
            'submitted_fps': result['metrics']['playing']['submitted_fps'],
            'presented_video_fps': observed['compositor_presented_video_fps'],
            'current_mode_refresh_hz': observed['compositor_refresh_hz'],
            'full_source_rate_gate_passed': result['smoothness_passed'],
        })

    stock = read('BiliP011-StockRestoreAudit-20260925-154604')
    screen = read('BiliP011-Screen-20260925-154456')
    idle = {'auto_screen_off_enabled': 1, 'screen_off_seconds': 60}
    if (stock['passed'] is not True or stock['active_private_processes'] != 0 or
            stock['stock']['hashes'] != STOCK_HASHES or screen['vendor_idle_fields'] != idle or
            screen['stock_hashes_unchanged'] is not True or screen['stock_processes_unchanged'] is not True):
        raise ValueError('Final original identity/idle check failed')
    # Exact process identity and parent-chain details remain in local raw logs.
    files['recovery.json'] = encode({
        'passed': True, 'active_private_processes': 0, 'stock_hashes': STOCK_HASHES,
        'stock_and_parent_identity_verified': True, 'vendor_idle_fields': idle,
        'screen_check_run': 'BiliP011-Screen-20260925-154456',
        'independent_check_run': 'BiliP011-StockRestoreAudit-20260925-154604',
        'default_media': 'media-e4ccc8fa53004efb', 'default_promoted': False,
        'system_files_changed': False, 'frequency_changed': False, 'device_rebooted': False,
    })
    files['summary.json'] = encode({
        'schema': 1, 'scope': 'presentation_and_driver_level_observation',
        'player_runs': player_summaries, 'physical_optical_measurement': False,
        'physical_acceptance': False, 'stable_display_ceiling_playback_passed': False,
        'soc_absolute_decode_ceiling_established': False, 'permanent_install': False,
        'driver_level_is_not_physical_mhz': True, 'child_sha256': CHILDREN,
        'source_scope': 'diagnostic_changes_not_complete_build_distribution',
    })
    files['PRIVACY.txt'] = (
        'Includes pinned safe child archives, public test-video captures, diagnostic sources and selected restoration fields.\n'
        'Excludes factory binaries/raw factory logs, account data, QR content, cookies and signed media URLs.\n'
        'Original local evidence is retained; failed full-rate and first empty-readback results are not reclassified.\n'
    ).encode('ascii')
    hashes = {name: hashlib.sha256(body).hexdigest() for name, body in files.items()}
    target = LOGS / ('BiliP011-Presentation-Comparison-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '-safe.zip')
    with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as archive:
        for name, body in sorted(files.items()):
            archive.writestr(name, body)
        archive.writestr('SHA256.json', encode(hashes))
    with zipfile.ZipFile(target) as archive:
        if (archive.testzip() is not None or set(archive.namelist()) != set(files) | {'SHA256.json'} or
                any(hashlib.sha256(archive.read(name)).hexdigest() != sha for name, sha in hashes.items())):
            raise ValueError('Combined evidence readback differs')
    print('SAFE_RESULT_ZIP=' + str(target))
    print('ZIP_SHA256=' + hashlib.sha256(target.read_bytes()).hexdigest())
    print('FILES=' + str(len(files)))


if __name__ == '__main__':
    main()
