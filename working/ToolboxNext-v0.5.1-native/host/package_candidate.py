"""Freeze the exact host/device-verified native candidate and selected evidence."""
import argparse
import hashlib
import json
import pathlib
import zipfile

BASE=pathlib.Path(__file__).resolve().parents[1]


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('host-result','device-result','manual-result','report','out'):
        parser.add_argument('--'+name,required=True,type=pathlib.Path)
    args=parser.parse_args()
    host=read_json(args.host_result/'result.json')
    assert host['passed'] and not host['adb_invoked']
    for row in read_json(args.host_result/'source-manifest.json'):
        assert hashlib.sha256((BASE/row['path']).read_bytes()).hexdigest()==row['sha256'],'Changed since host verification: '+row['path']
    device=read_json(args.device_result/'result.json')
    manual=read_json(args.manual_result/'result.json')
    for result in (device,manual):
        for name in ('stock_hashes_unchanged','stock_processes_unchanged','own_ui_closed',
                     'loopback_closed','serve_closed','sampler_closed','transfer_closed','audio_closed'):
            assert result[name],name
    assert device['passed'] and device['automated'] and device['ui_exit']==0
    assert not manual['automated']
    deployed={}
    for folder in ('runtime','device','web'):
        for file in sorted((BASE/folder).iterdir()):
            if file.is_file() and file.suffix in ('.py','.qml','.js','.html','.css','.svg'):
                deployed[file.relative_to(BASE).as_posix()]=file.read_bytes()
    target_manifest=''.join(hashlib.sha256(data).hexdigest()+' '+str(len(data))+' '+name+'\n'
                            for name,data in sorted(deployed.items())).encode('ascii')
    target_id=hashlib.sha256(target_manifest).hexdigest()
    assert device['source_identity']==manual['source_identity']==target_id,'Device evidence belongs to different source'
    entries={}
    prefix='ToolboxNext-v0.5.1-native/'
    def add(file,name):
        assert file.is_file() and not file.is_symlink()
        assert name not in entries
        entries[name]=file.read_bytes()
    for file in sorted(BASE.iterdir()):
        if file.is_file() and file.suffix.lower() in ('.md','.cmd'):
            add(file,prefix+file.name)
    for folder in ('runtime','device','web','host','tests'):
        for file in sorted((BASE/folder).rglob('*')):
            if file.is_file() and '__pycache__' not in file.parts:
                assert file.suffix.lower() in ('.py','.qml','.js','.html','.css','.svg','.txt','.md')
                add(file,prefix+file.relative_to(BASE).as_posix())
    entries[prefix+'SOURCE.sha256']=target_manifest
    for file in sorted(args.host_result.rglob('*')):
        if file.is_file():add(file,'Evidence/host/'+file.relative_to(args.host_result).as_posix())
    # Automated directory contains only synthetic fixtures and our own page images.
    for file in sorted((args.device_result/'device').rglob('*')):
        if file.is_file():add(file,'Evidence/device-ui/'+file.relative_to(args.device_result/'device').as_posix())
    add(args.device_result/'result.json','Evidence/device-ui-result.json')
    # Manual raw logs stay in the owner's workspace; archive only fixed-event/
    # process-identity summary, not potential media decoder paths or user files.
    add(args.manual_result/'result.json','Evidence/manual-session-result.json')
    add(args.report,'Evidence/verification-report.md')
    manifest={'candidate':'v0.5.1-native','status':'finite native UI trial; not a permanent factory-menu installation',
              'target_source_identity_sha256':target_id,
              'files':[{'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
                       for name,data in sorted(entries.items())]}
    args.out.mkdir(parents=True,exist_ok=True)
    archive=args.out/('P011-ToolboxNative-v0.5.1-CANDIDATE-'+target_id[:12]+'.zip')
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as bundle:
        for name,data in sorted(entries.items()):bundle.writestr(name,data)
        bundle.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8'))
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        for row in manifest['files']:assert hashlib.sha256(bundle.read(row['path'])).hexdigest()==row['sha256']
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    with archive.with_suffix('.sha256').open('x',encoding='ascii') as handle:handle.write(digest+'  '+archive.name+'\n')
    print('CANDIDATE_ZIP='+str(archive));print('TARGET_SOURCE_ID='+target_id)
    print('ZIP_SHA256='+digest);print('ARCHIVE_FILES='+str(len(entries)+1));print('CRC_AND_ALL_FILE_HASHES=PASS')


if __name__=='__main__':main()
