"""Whitelist Story evidence, sources and reviewed public screenshots."""
import argparse,datetime,hashlib,json,pathlib,zipfile
from build_awake_trial import BASE,ROOT
from strip_player_artifact import validate_strip_player

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--supporting',action='append',default=[])
    p.add_argument('--failed',action='append',default=[]);p.add_argument('--screen',required=True)
    p.add_argument('--audit',required=True);p.add_argument('--units',required=True);p.add_argument('--qt',required=True)
    a=p.parse_args();validate_strip_player(BASE);files={};verdicts=[]
    def folder(name):
        if pathlib.Path(name).name!=name or not name.startswith('BiliP011-'):raise ValueError('Evidence name')
        path=ROOT/'logs'/name
        if path.is_symlink() or not path.is_dir():raise ValueError('Evidence directory')
        return path
    for role,names in (('required',[a.run]),('supporting',a.supporting),('retained-failure',a.failed)):
        for name in names:
            directory=folder(name);report=json.loads((directory/'result.json').read_text(encoding='utf-8'))
            if not report.get('recovery_passed'):raise ValueError('Unconfirmed recovery')
            if role!='retained-failure' and (not report.get('ui_automation',{}).get('passed') or report.get('host_error') or report.get('recovery_error')):raise ValueError('Unpassed trial')
            verdicts.append(dict(run=name,role=role,passed=bool(report.get('ui_automation',{}).get('passed')),recovery_passed=True))
            with zipfile.ZipFile(directory.with_name(name+'-safe.zip')) as z:
                if z.testzip():raise ValueError('Corrupt archive')
                for row in z.infolist():
                    rel=pathlib.PurePosixPath(row.filename)
                    if rel.is_absolute() or '..' in rel.parts or '\\' in row.filename or row.file_size>8*1024*1024:raise ValueError('Unsafe entry')
                    if rel.suffix.lower() in ('.raw','.exe','.ttf','.ttc','.mp4','.mp3','.cookie') or 'account' in row.filename.lower():raise ValueError('Private entry')
                    files[name+'/'+row.filename]=z.read(row)
            if (directory/'SCREENSHOTS.html').is_file():files[name+'/SCREENSHOTS.html']=(directory/'SCREENSHOTS.html').read_bytes()
    screen=folder(a.screen);report=json.loads((screen/'result.json').read_text(encoding='utf-8'))
    meta=json.loads((folder(a.run)/'bundle.json').read_text(encoding='utf-8'))
    if not(report.get('passed') and report.get('state_stable') and report['sample']['context']['session']==meta['session']):raise ValueError('Screen identity')
    for name in ('result.json','scanout/00.png','scanout/00.json'):files['screen/'+name]=(screen/name).read_bytes()
    for role,name in (('audit',a.audit),('units',a.units),('qt',a.qt)):
        directory=folder(name);r=json.loads((directory/'result.json').read_text(encoding='utf-8'))
        if role=='audit' and not(r.get('passed') and r.get('active_private_processes')==0):raise ValueError('Audit failed')
        if role=='units' and r.get('host_exit')!=0:raise ValueError('Units failed')
        if role=='qt' and not(r.get('passed') and r.get('device_tested') is False):raise ValueError('Qt failed')
        files[role+'/result.json']=(directory/'result.json').read_bytes()
        if role=='units':files[role+'/summary.txt']=(directory/'stderr.raw').read_bytes()
    sources=('client/media_range.hpp','client/media_prefix.hpp','client/media_relay.py','client/cached_media.hpp',
        'client/api.cpp','client/player.cpp','client/player_v2.cpp','client/hardware_worker.cpp','client/player_controls.hpp',
        'client/story.py','client/story_cache.py','client/service.py','client/story_probe.py','client/BiliStoryAutomation.qml',
        'client/BiliPanel.qml','client/BiliLibrary.qml','host/story_trial.py','host/story_peek.py','host/story_screen.py',
        'host/build_awake_trial.py','host/media_range_test.cpp','host/test_media_relay.py','host/test_story_cache.py','host/test_story_probe.py',
        'host/player_controls_test.cpp','host/test_hardware_allocation.py','host/strip_player_artifact.py','host/test_strip_player_artifact.py',
        'host/review_gallery.py','host/preview_features.py','host/package_story_delivery.py','build/build_strip_player.py',
        'TEST_BILI_STORY.cmd','TEST_BILI_STORY_AUTO.cmd')
    for name in sources:files['source/'+name]=(BASE/name).read_bytes()
    files['native-build-manifest.json']=(BASE/'out/strip-player.build.json').read_bytes()
    files['REPORT.md']=(ROOT/'04_Documents/P011-Bili短视频预加载与操作优化-20260927.md').read_bytes()
    files['VERDICTS.json']=json.dumps(dict(runs=verdicts,physical_acceptance=False,zero_latency_proven=False,full_regression=False),indent=2).encode()
    files['README.txt']=('P011 Story 预加载专项。先读 REPORT.md 与 VERDICTS.json。\n'
        'required 为最终专项，supporting 为较早通过轮次，retained-failure 保留失败原判。\n'
        'screen 是未变换的480x800真实DRM采集；ui-crops 是应用截图，不可混作同一层证据。\n'
        '仅含白名单源码、数值报告和公开页面图；无凭据、签名URL、raw、字体、媒体缓存或原厂二进制。\n'
        '依赖原工作区运行，不是独立安装包或恢复镜像；没有证明零等待、全部功能或人工听感通过。\n').encode('utf-8')
    manifest={name:dict(bytes=len(body),sha256=hashlib.sha256(body).hexdigest()) for name,body in files.items()}
    files['MANIFEST.json']=json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8')
    target=ROOT/'logs'/('BiliP011-Story-Delivery-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-safe.zip')
    with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED) as z:
        for name,body in sorted(files.items()):z.writestr(name,body)
    with zipfile.ZipFile(target) as z:
        if z.testzip() or set(z.namelist())!=set(files):raise ValueError('ZIP CRC/names')
        for name,row in manifest.items():
            data=z.read(name)
            if len(data)!=row['bytes'] or hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('ZIP hash')
    print('SAFE_RESULT_ZIP='+str(target));print('SHA256='+hashlib.sha256(target.read_bytes()).hexdigest());print('FILES='+str(len(files)))
if __name__=='__main__':main()
