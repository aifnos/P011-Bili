"""Package reviewed, sanitized alignment evidence; no device/account raw data."""
import argparse,datetime,hashlib,json,pathlib,zipfile
from build_awake_trial import BASE,ROOT

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',action='append',required=True)
    p.add_argument('--failed',action='append',default=[]);p.add_argument('--supporting-run',action='append',default=[]);p.add_argument('--audit',required=True)
    p.add_argument('--units',required=True);p.add_argument('--protocol',required=True);p.add_argument('--pose-qa',required=True)
    a=p.parse_args();files={};verdicts=[];required_profiles=set();required_sessions=set();required_media=set()
    def directory(name):
        if pathlib.Path(name).name!=name or not name.startswith('BiliP011-'):raise ValueError('Evidence name')
        result=ROOT/'logs'/name
        if not result.is_dir() or result.is_symlink():raise ValueError('Evidence directory')
        return result
    for role,names in (('required',a.run),('supporting',a.supporting_run),('retained-failure',a.failed)):
        for name in names:
            folder=directory(name);report=json.loads((folder/'result.json').read_text(encoding='utf-8'))
            if not report.get('recovery_passed'):raise ValueError('Unconfirmed stock recovery')
            if role!='retained-failure' and any(report.get(k) for k in ('host_error','recovery_error','recovery_or_result_error')):raise ValueError('Unresolved trial error')
            if role!='retained-failure' and not (report.get('ui_automation',{}).get('passed') or report.get('passed')):raise ValueError('Supporting checks not passed')
            if role=='required' and not report.get('screen_alignment',{}).get('passed'):raise ValueError('Real screen checks not passed')
            if role=='required':
                meta=json.loads((folder/'bundle.json').read_text(encoding='utf-8'))
                required_profiles.add(report['screen_alignment'].get('profile','full-regression'))
                required_sessions.add(meta['session']);required_media.add(meta['media_remote'])
            verdicts.append(dict(run=name,role=role,retained_failure=role=='retained-failure',screen_passed=report.get('screen_alignment',{}).get('passed',False)))
            with zipfile.ZipFile(folder.with_name(name+'-safe.zip')) as z:
                if z.testzip():raise ValueError('Corrupt safe archive')
                for item in z.infolist():
                    rel=pathlib.PurePosixPath(item.filename)
                    if rel.is_absolute() or '..' in rel.parts or '\\' in item.filename or item.file_size>8*1024*1024:raise ValueError('Unsafe evidence entry')
                    if rel.suffix.lower() in ('.raw','.exe','.ttf','.ttc','.mp4','.mp3','.cookie') or 'account' in item.filename.lower():raise ValueError('Private evidence payload')
                    files[name+'/'+item.filename]=z.read(item)
            if (folder/'SCREENSHOTS.html').is_file():files[name+'/SCREENSHOTS.html']=(folder/'SCREENSHOTS.html').read_bytes()
    if len(required_media)!=1 or not ('full-regression' in required_profiles or required_profiles=={'landscape','portrait'} and len(required_sessions)>=2):
        raise ValueError('Need both orientations and repeated windows for one exact media')
    for label,name in (('audit',a.audit),('units',a.units),('protocol',a.protocol),('pose-qa',a.pose_qa)):
        folder=directory(name)
        report=json.loads((folder/'result.json').read_text(encoding='utf-8'))
        if label=='audit' and (report.get('passed') is not True or report.get('active_private_processes')!=0):raise ValueError('Final restoration audit failed')
        if label=='units' and report.get('host_exit')!=0:raise ValueError('Host checks failed')
        if label=='pose-qa':
            qt=json.loads((folder/'stdout.raw').read_text(encoding='utf-8'))
            if report.get('host_exit')!=0 or qt.get('passed') is not True or qt.get('device_tested') is not False or len(qt.get('checks',[]))!=8:raise ValueError('Qt sampling test failed')
            files[label+'/qt-result.json']=json.dumps(qt,indent=2).encode()
        if label=='protocol' and report.get('read_only') is not True:raise ValueError('Protocol diagnostic not read-only')
        files[label+'/result.json']=(folder/'result.json').read_bytes()
        if label=='units':files[label+'/test-summary.txt']=(folder/'stderr.raw').read_bytes()
    for name in ('client/player_v2.cpp','client/wayland_presentation.hpp','client/PlayerAutomation.qml','client/BiliPerformance.qml',
                 'third_party/SDL2-2.0.8-p011/src/video/wayland/SDL_waylandvideo.c',
                 'third_party/SDL2-2.0.8-p011/src/video/wayland/SDL_waylandwindow.c',
                 'third_party/SDL2-2.0.8-p011/src/video/wayland/SDL_waylandwindow.h',
                 'third_party/SDL2-2.0.8-p011/COPYING.txt',
                 'host/scanout_alignment.py','host/test_scanout_alignment.py','host/test_centered_window.py',
                 'host/window_placement_trial.py','host/client_oneclick.py','host/client_results.py','host/build_awake_trial.py',
                 'host/test_client_results.py','host/package_window_fix.py','build/build_sdl_probe.py',
                 'host/check_window_pose_hold.py','host/performance_trial.py',
                 'host/capture_drm_scanout.py','host/window_protocol_info.py',
                 'TEST_BILI_WINDOW_FIX.cmd','TEST_BILI_WINDOW_FIX_AUTO.cmd',
                 'TEST_BILI_EXPANDED.cmd','TEST_BILI_EXPANDED_AUTO.cmd'):
        files['source/'+name]=(BASE/name).read_bytes()
    doc=ROOT/'04_Documents/P011-Bili播放窗口错位修复-20260927.md'
    files['REPORT.md']=doc.read_bytes()
    files['native-build-manifest.json']=(BASE/'out/strip-player.build.json').read_bytes()
    files['README.txt']=('P011 Bili 播放窗口定位修复证据包\n\n先读 REPORT.md 和 VERDICTS.json。\n'
        'required 是定位专项：必须包含同一媒体、横竖屏两个独立恢复会话，或一个覆盖两姿态与两代播放器的完整回归。不是全部功能通过声明。\n'
        'supporting 是独立短播放或功能检查，不自动升级为屏幕定位通过。\n'
        'retained-failure 保留失败或覆盖不足判定，不能与通过记录混算。\n'
        'scanout 为未旋转、未修图的 480x800 DRM 输出；ui-crops 为应用截图，二者不是同一种证据。\n'
        'cmd 依赖原工作区和 ADB。本包不是安装包、固件或完整恢复镜像。\n'
        '原始 raw 日志、账号、凭据、缓存媒体和字体未包含。真实声音、触摸与手持体验待本人确认。\n').encode('utf-8')
    files['VERDICTS.json']=json.dumps({'runs':verdicts,'physical_touch_tested':False,'standalone_installation':False},indent=2).encode()
    manifest={n:dict(bytes=len(b),sha256=hashlib.sha256(b).hexdigest()) for n,b in files.items()}
    files['MANIFEST.json']=json.dumps(manifest,indent=2,ensure_ascii=False).encode('utf-8')
    path=ROOT/'logs'/('BiliP011-WindowFix-Delivery-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-safe.zip')
    with zipfile.ZipFile(path,'x',zipfile.ZIP_DEFLATED) as z:
        for name,body in sorted(files.items()):z.writestr(name,body)
    with zipfile.ZipFile(path) as z:
        if z.testzip() or set(z.namelist())!=set(files):raise ValueError('ZIP verification')
        for n,m in manifest.items():
            raw=z.read(n)
            if len(raw)!=m['bytes'] or hashlib.sha256(raw).hexdigest()!=m['sha256']:raise ValueError('ZIP hash mismatch')
    print('SAFE_RESULT_ZIP='+str(path));print('SHA256='+hashlib.sha256(path.read_bytes()).hexdigest())
    print('FILES='+str(len(files)))

if __name__=='__main__':main()
