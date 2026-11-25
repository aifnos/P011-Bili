"""Read-only integrity/privacy and evidence-layer audit of an expanded ZIP."""
import argparse
import hashlib
import json
import pathlib
import posixpath
import re
import zipfile
from html.parser import HTMLParser

from build_awake_trial import BASE, ROOT


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = []

    def handle_starttag(self, tag, attrs):
        if tag == 'img':
            self.images.extend(value for key, value in attrs if key == 'src')


def verify(path):
    path = path.resolve()
    if path.parent != ROOT / 'logs' or not re.fullmatch(
            r'BiliP011-Expanded-Delivery-\d{8}-\d{6}-safe\.zip', path.name):
        raise ValueError('Expected explicit workspace delivery ZIP')
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or archive.testzip():
            raise ValueError('ZIP duplicate or CRC failure')
        manifest = json.loads(archive.read('MANIFEST.json'))
        expected = set(manifest['files']) | {'MANIFEST.json', 'PRIVACY.txt'}
        if expected != set(names):
            raise ValueError('ZIP manifest coverage')
        image_refs = 0
        for name in names:
            n = pathlib.PurePosixPath(name)
            if n.is_absolute() or '..' in n.parts or '\\' in name:
                raise ValueError('Unsafe archive path')
            data = archive.read(name)
            if name in manifest['files'] and hashlib.sha256(data).hexdigest() != manifest['files'][name]:
                raise ValueError('File hash mismatch: ' + name)
            if n.suffix.lower() in ('.raw', '.cookie', '.exe', '.ttf', '.ttc', '.mp4', '.mp3'):
                raise ValueError('Unexpected payload type: ' + name)
            if n.suffix.lower() in ('.json', '.jsonl', '.txt', '.md', '.html', '.cmd'):
                text = data.decode('utf-8')
                # Match credential values/headers, not prose mentioning field names.
                private = (r'(?:SESSDATA|bili_jct|DedeUserID)\s*[=\t]\s*[A-Za-z0-9%_-]{6,}',
                           r'Authorization:\s*(?:Bearer|Basic)\s+\S+',
                           r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
                           r'https?://[^\s"<>]+[?&](?:deadline|upsig|wsSecret|access_key|refresh_token)=')
                if any(re.search(pattern, text, re.I) for pattern in private):
                    raise ValueError('Potential private material; inspect locally: ' + name)
            if n.suffix.lower() == '.html':
                refs = References()
                refs.feed(data.decode('utf-8'))
                for ref in refs.images:
                    target = posixpath.normpath(posixpath.join(posixpath.dirname(name), ref))
                    if target not in expected or target.startswith('../'):
                        raise ValueError('Broken or external gallery reference: ' + name)
                    image_refs += 1
        checks = captures = 0
        for label in ('catalog', 'features', 'regression'):
            result = json.loads(archive.read(label + '/result.json'))
            bundle = json.loads(archive.read(label + '/bundle.json'))
            if not bundle['media_local'].endswith('media-3f81b61a4e31ce9e'):
                raise ValueError('Unexpected final media identity')
            if result['ui_automation']['passed'] is not True or result['recovery_passed'] is not True:
                raise ValueError('Final trial not passed/restored')
            # The integrated trial keeps UI, native player and toolbox assertions
            # in separate arrays; specialty trials only have the first array.
            checks += sum(len(result['ui_automation'].get(key, []))
                          for key in ('checks', 'player_checks', 'toolbox_checks'))
            captures += result['capture_count']
        if (checks, captures) != (124, 61):
            raise ValueError('Final evidence counts differ from report')
        if manifest['account_writes_tested'] or manifest['physical_acceptance'] or manifest['known_quality_switch_timeout_resolved']:
            raise ValueError('Unsupported evidence upgrade')
        audit = json.loads(archive.read('audit/result.json'))
        account = json.loads(archive.read('account-readonly/result.json'))
        qt = json.loads(archive.read('qt/result.json'))
        if not audit['passed'] or audit['active_private_processes'] or audit['webengine_processes']:
            raise ValueError('Final restoration not confirmed')
        if not account['passed'] or account['account_writes'] or account['account_screenshots']:
            raise ValueError('Account scope mismatch')
        if not qt['passed'] or qt['warnings'] or len(qt['checks']) != 50 or len(qt['captures']) != 22:
            raise ValueError('Qt evidence mismatch')
        if not re.search(r'Ran 522 tests\b', archive.read('units/stderr.txt').decode('utf-8')):
            raise ValueError('Missing final host test evidence')
        native = json.loads(archive.read('native-build-manifest.json'))
        for name, digest in native['sources'].items():
            source = BASE / name
            if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
                raise ValueError('Native source drift: ' + name)
    return dict(passed=True, device_tested=False, layer='PC archive integrity and evidence audit',
                files=len(names), gallery_image_references=image_refs,
                final_device_checks=checks, final_public_captures=captures,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('zip_path', type=pathlib.Path)
    print(json.dumps(verify(parser.parse_args().zip_path), ensure_ascii=False, indent=2))
