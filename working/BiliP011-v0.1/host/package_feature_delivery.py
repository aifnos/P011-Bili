"""Package already-sanitized evidence, never raw device/account directories."""
import argparse
import datetime
import hashlib
import json
import pathlib
import zipfile
from build_awake_trial import BASE, ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--features', required=True)
    parser.add_argument('--regression', required=True)
    parser.add_argument('--audit', required=True)
    parser.add_argument('--units', required=True)
    parser.add_argument('--qt', required=True)
    parser.add_argument('--feature-qt', required=True)
    parser.add_argument('--integrated-qt', required=True)
    parser.add_argument('--failed', action='append', default=[])
    args = parser.parse_args()
    files = {}
    verdicts = {}

    def directory(name):
        if pathlib.Path(name).name != name or not name.startswith('BiliP011-'):
            raise ValueError('Expected one local evidence directory name')
        path = ROOT / 'logs' / name
        if not path.is_dir() or path.is_symlink():
            raise ValueError('Missing evidence directory')
        return path

    for label, name in [('features', args.features), ('regression', args.regression)] + [('retained-failure-%d' % i, n) for i, n in enumerate(args.failed)]:
        run = directory(name)
        result = json.loads((run / 'result.json').read_text(encoding='utf-8'))
        if not result.get('recovery_passed'):
            raise ValueError('Stock restoration must be confirmed before delivery')
        verdicts[label] = {'directory': name, 'passed': result.get('ui_automation', {}).get('passed') is True,
                           'recovery_passed': True, 'physical_acceptance': False}
        # These archives were generated with client_results' fixed allowlist.
        archive = run.with_name(run.name + '-safe.zip')
        if archive.is_symlink():
            raise ValueError('Unexpected symlink')
        with zipfile.ZipFile(archive) as z:
            if z.testzip() is not None:
                raise ValueError('Corrupt sanitized archive')
            for item in z.infolist():
                p = pathlib.PurePosixPath(item.filename)
                if p.is_absolute() or '..' in p.parts or '\\' in item.filename or item.file_size > 8 * 1024 * 1024:
                    raise ValueError('Unsafe archive entry')
                if p.suffix.lower() in ('.raw', '.cookie', '.exe', '.ttf', '.ttc', '.mp4', '.mp3') or 'account' in item.filename.lower():
                    raise ValueError('Private payload not permitted')
                files[label + '/' + item.filename] = z.read(item)
        if (run / 'SCREENSHOTS.html').is_file():
            files[label + '/SCREENSHOTS.html'] = (run / 'SCREENSHOTS.html').read_bytes()

    for label, name in [('audit', args.audit), ('units', args.units), ('qt', args.qt), ('feature-qt', args.feature_qt), ('integrated-qt', args.integrated_qt), ('account-readonly', 'BiliP011-AccountReadOnly-20260926-175134')]:
        run = directory(name)
        result = json.loads((run / 'result.json').read_text(encoding='utf-8'))
        if label == 'audit' and (result.get('passed') is not True or result.get('active_private_processes') != 0):
            raise ValueError('Final independent audit not passed')
        if label in ('qt', 'feature-qt', 'integrated-qt', 'account-readonly') and result.get('passed') is not True:
            raise ValueError('Required host/read-only checks failed')
        if label == 'units' and result.get('host_exit') != 0:
            raise ValueError('Unit tests failed')
        files[label + '/result.json'] = (run / 'result.json').read_bytes()
        # Unit runner output is host-only and contains no API/account payloads.
        if label == 'units':
            files[label + '/stderr.txt'] = (run / 'stderr.raw').read_bytes()
        if label == 'feature-qt':
            for stem in ('01-live-catalog', '02-live-detail', '03-interactions', '04-coin-confirm',
                         '05-favorites', '06-cloud-history', '07-password-empty', '08-password-masked'):
                files['synthetic-account-ui/' + stem + '.png'] = (run / (stem + '.png')).read_bytes()

    files['REPORT.md'] = (ROOT / '04_Documents/P011-Bili官方功能扩展与验收-20260926.md').read_bytes()
    files['native-build-manifest.json'] = (BASE / 'out/strip-player.build.json').read_bytes()
    files['official-source-index.json'] = (ROOT / 'logs/BiliP011-OfficialFeatureSources-20260926-170412/sources.json').read_bytes()
    for name in ('TEST_BILI_FEATURES.cmd', 'TEST_BILI_FEATURES_AUTO.cmd'):
        files['entrypoints/' + name] = (BASE / name).read_bytes()
    summary = {'schema': 1, 'verdicts': verdicts, 'account_writes_tested': False,
               'password_login_verified': False, 'physical_acceptance': False,
               'official_recommendation_feedback_implemented': False,
               'files': {n: hashlib.sha256(b).hexdigest() for n, b in sorted(files.items())}}
    files['MANIFEST.json'] = json.dumps(summary, ensure_ascii=False, indent=2).encode('utf-8')
    files['PRIVACY.txt'] = ('Only allowlisted public device captures, synthetic account previews, numeric results and source identities. '
                            'No raw factory logs, credentials, QR, account contents, signed media URLs, media cache, stock binaries or fonts. '
                            'Retained failures remain failures; machine checks are not physical/account acceptance.\n').encode('utf-8')
    out = ROOT / 'logs' / ('BiliP011-Features-Delivery-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '-safe.zip')
    with zipfile.ZipFile(out, 'x', zipfile.ZIP_DEFLATED) as z:
        for name, body in sorted(files.items()):
            z.writestr(name, body)
    with zipfile.ZipFile(out) as z:
        if z.testzip() is not None or set(z.namelist()) != set(files):
            raise ValueError('Delivery archive verification failed')
    print('SAFE_RESULT_ZIP=' + str(out))
    print('ZIP_SHA256=' + hashlib.sha256(out.read_bytes()).hexdigest())
    print('FILES=' + str(len(files)))


if __name__ == '__main__':
    main()
