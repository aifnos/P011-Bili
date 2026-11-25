"""PC-only packaging of the fixed 2026-09-25 screen-rate comparison evidence."""
import datetime
import hashlib
import json
from pathlib import Path
import zipfile

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parents[1]
LOGS = ROOT / 'logs'
REPORT = ROOT / '04_Documents/P011-Bili屏幕适配高帧率对照-20260925.md'


def read(name):
    return json.loads((LOGS / name / 'result.json').read_bytes())


def encode(value):
    return json.dumps(value, ensure_ascii=True, indent=2).encode('ascii')


def main():
    files = {'REPORT.md': REPORT.read_bytes()}
    for stamp in ('143855', '144120', '144152', '144246'):
        name = 'BiliP011-ScreenRate-20260925-' + stamp
        # These fixed generated-fixture result files contain numeric metrics,
        # explicit test scope, hashes and bounded error categories only.
        row = read(name)
        if row.get('synthetic') is not True or row.get('bili_stream_tested') is not False:
            raise ValueError('Wrong decoder result scope')
        files['decoder/' + stamp + '.json'] = encode(row)
    for stamp in ('142459', '142737', '143942'):
        name = 'BiliP011-PerformanceTrial-20260925-' + stamp
        row = read(name)
        keys = ('metrics', 'passed', 'passed_scope', 'smoothness_evaluated', 'smoothness_passed',
                'high_fps_compatibility_passed', 'rate_states_verified', 'recovery_passed',
                'output_cache_required', 'output_cache_verified', 'physical_acceptance', 'permanent_install')
        files['player/' + stamp + '.json'] = encode({k: row[k] for k in keys if k in row})
        files['screenshots/' + stamp + '.png'] = (LOGS / name / 'device/screenshots/player-landscape.png').read_bytes()
    for stamp in ('142407', '142631'):
        row = read('BiliP011-QualityInventory-20260925-' + stamp)
        # No account result, title, user information or signed stream URL.
        files['inventory/' + stamp + '.json'] = encode({
            'variants': [{k: entry[k] for k in ('quality', 'codec', 'width', 'height')} for entry in row['variants']],
            'playback_started': row['playback_started'],
            'account_content_exported': row['account_content_exported'],
        })
    stock = read('BiliP011-StockRestoreAudit-20260925-144322')
    screen = read('BiliP011-Screen-20260925-144316')
    raw_mode = (LOGS / 'BiliP011-Screen-20260925-144316/wayland-registry.stdout.raw').read_bytes()
    if b'width: 480 px, height: 800 px, refresh: 55.202 Hz' not in raw_mode:
        raise ValueError('Mode evidence differs')
    files['recovery.json'] = encode({
        'passed': stock['passed'], 'active_private_processes': stock['active_private_processes'],
        'stock_hashes': stock['stock']['hashes'], 'stock_processes_verified': stock['passed'],
        'idle': screen['vendor_idle_fields'], 'screen_stock_hashes_unchanged': screen['stock_hashes_unchanged'],
        'reported_mode': {'width': 480, 'height': 800, 'transform': 270, 'refresh_hz': 55.202},
        'physical_refresh_measured': False, 'default_media_unchanged': 'media-e4ccc8fa53004efb',
    })
    host_name = 'BiliP011-PerformanceHost-20260925-144331-017585'
    host = read(host_name)
    files['host-tests.json'] = encode(host)
    files['host-tests.stderr.raw'] = (LOGS / host_name / 'tests.stderr.raw').read_bytes()
    for name in ('host/screen_rate_trial.py', 'host/test_screen_rate_trial.py',
                 'host/package_screen_rate_comparison.py', 'TEST_BILI_SCREEN_60FPS.cmd'):
        files['sources/' + name] = (BASE / name).read_bytes()
    manifest = {name: hashlib.sha256(body).hexdigest() for name, body in files.items()}
    archive = LOGS / ('BiliP011-ScreenRate-Comparison-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '-safe.zip')
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as z:
        for name, body in files.items():
            z.writestr(name, body)
        z.writestr('SHA256.json', encode(manifest))
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None or any(hashlib.sha256(z.read(name)).hexdigest() != sha for name, sha in manifest.items()):
            raise ValueError('Evidence archive readback differs')
    print('SAFE_RESULT_ZIP=' + str(archive))
    print('ZIP_SHA256=' + hashlib.sha256(archive.read_bytes()).hexdigest())
    print('FILES=' + str(len(files)))


if __name__ == '__main__':
    main()
