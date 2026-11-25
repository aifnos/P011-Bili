"""Run fixed, non-mutating feasibility diagnostics without launching the UI."""
import argparse
import datetime
import hashlib
import json
import pathlib

from awake_trial import Adb, ROOT, result_from, check_bundle

BASE = pathlib.Path(__file__).resolve().parent
GROUPS = ('public','account','media','live','followup','subtitles','pagination')


def remote_code(group, runtime, hashes):
    if group not in GROUPS:
        raise ValueError('Unknown read-only group')
    common = (BASE/'feature_feasibility_device.py').read_text(encoding='utf-8')
    branches = common.split("    if GROUP == 'public':",1)
    body = branches[1].split("    elif GROUP == ")
    group_code = {'public':body[0]}
    for part in body[1:]:
        key, value = part.split("':\n",1)
        group_code[key.strip("'")] = value
    group_code['pagination'] = group_code['pagination'].split('    else:\n        raise ValueError',1)[0]
    tail = common.split('\nfinally:\n',1)[1]
    header = 'RUNTIME='+repr(runtime)+'\nVERIFIED_FILES='+repr(hashes)+'\nGROUP='+repr(group)+'\n'
    code = header+branches[0]+'    if True:\n'+group_code[group]+'\nfinally:\n'+tail
    compile(code, '<read-only-feasibility>', 'exec')
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group', required=True, choices=GROUPS)
    parser.add_argument('--bundle', type=pathlib.Path, required=True)
    args = parser.parse_args()
    meta, _ = check_bundle(args.bundle)
    out = ROOT/'logs'/('BiliP011-Feasibility-'+args.group+'-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir()
    print('LOG_DIR='+str(out), flush=True)
    hashes = {name:hashlib.sha256((args.bundle/name).read_bytes()).hexdigest()
              for name in ('stdlib-json35.zip','native_safety.py')}
    # Only ship the requested fixed branch so legacy ADB stays under 4 KiB.
    code = remote_code(args.group, meta['remote'], hashes)
    report = result_from(Adb(out).python('fixed-get-probes',code,timeout=175))
    (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['stock_unchanged'] and report['credentials_unchanged'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
