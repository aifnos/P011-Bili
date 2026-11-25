"""One-click fixed installed-worker repair through the existing ADB channel."""
import argparse
import ast
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import zipfile

HERE=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['inspect','apply'])
    args=parser.parse_args()
    expected=json.loads((HERE/'PACKAGE.json').read_bytes())
    for name,spec in expected.items():
        path=HERE/name
        assert not path.is_symlink() and path.is_file()
        assert path.stat().st_size==spec['bytes'] and hashlib.sha256(path.read_bytes()).hexdigest()==spec['sha256'],name
    patch=json.loads((HERE/'patch.json').read_bytes())
    spec=importlib.util.spec_from_file_location('legacy_patch_reader',HERE/'legacy_reader.py')
    reader=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    out=HERE.parent/('P011-Bili-PlaybackFix-'+args.action+'-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    out.mkdir()
    report=dict(passed=False,action=args.action,physical_acceptance=False)
    adb=reader.Adb(out)
    try:
        rows=adb.run('devices',['devices','-l'])
        targets=re.findall(r'^\S+\s+device\s+.*model:sprdisk .*transport_id:(\d+)',rows,re.M)
        assert len(targets)==1,'Exactly one connected P011 required'
        adb.transport=int(targets[0])
        release='/mnt/data/p011-toolbox/bili-formal/releases/'+patch['release_id']
        helper=(HERE/'device_install_helpers.py').read_text(encoding='utf8')
        code='__file__='+repr(release+'/device_install.py')+'\n'+helper.replace('from __future__ import print_function\n','',1).rsplit("if __name__ == '__main__':",1)[0]
        code+='\nPATCH='+repr(patch)+'\n'+(HERE/'device_patch.py').read_text(encoding='utf8')
        before=reader.result(adb.python('preflight',code+'\nprint("RESULT="+repr(playback_inspect()),flush=True)\n',60))
        report['before']=before
        if args.action=='apply':
            stage='/mnt/data/p011-toolbox/bili-formal/playback-patches/'+patch['revision_sha256'][:24]
            prepare=code+'\ndirectory(FORMAL+"/playback-patches",True)\ndirectory('+repr(stage)+',True)\n'
            parents=sorted({str(Path(n).parent).replace('\\','/') for n in patch['order']} - {'.'})
            prepare+='\n'.join('directory('+repr(stage+'/'+parent)+',True)' for parent in parents)+'\n'
            prepare+='print("RESULT="+repr(dict(staging_ready=True)),flush=True)\n'
            reader.result(adb.python('prepare-stage',prepare))
            for name in patch['order']:
                adb.run('push-fixed-file',['push',str(HERE/'payload'/name),stage+'/'+name])
            print('原安装核对通过，开始备份并更新硬解程序和关联校验记录。',flush=True)
            report['device']=reader.result(adb.python('apply-worker-fix',code+'\napply_playback_patch()\n',90))
            assert report['device']['applied']
        report['passed']=True
    except Exception as exc:
        report['error']=type(exc).__name__+': '+str(exc)
        print(report['error'],flush=True)
    finally:
        (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        with zipfile.ZipFile(str(out)+'.private.zip','x',zipfile.ZIP_DEFLATED) as z:
            for p in out.iterdir():
                if p.is_file():z.write(p,p.name)
        print(json.dumps(dict(passed=report['passed'],logs=str(out),device=report.get('device'),before=report.get('before')),ensure_ascii=False),flush=True)
    raise SystemExit(0 if report['passed'] else 1)


if __name__=='__main__':main()
