"""Immutable expanded-feature evidence ZIP; public captures/synthetic accounts only."""
import argparse,datetime,hashlib,json,pathlib,zipfile
from build_awake_trial import BASE,ROOT

def main():
    p=argparse.ArgumentParser()
    for name in ('catalog','features','regression','audit','units','qt','account','report'):p.add_argument('--'+name,required=True)
    p.add_argument('--failed',action='append',default=[]);p.add_argument('--failed-qt',action='append',default=[])
    p.add_argument('--supporting-run',action='append',default=[])
    a=p.parse_args();files={};verdicts={}
    def directory(name):
        if pathlib.Path(name).name!=name or not name.startswith('BiliP011-'):raise ValueError('Expected local evidence identity')
        r=ROOT/'logs'/name
        if not r.is_dir() or r.is_symlink():raise ValueError('Missing evidence')
        return r
    for label,name in [('catalog',a.catalog),('features',a.features),('regression',a.regression)]+[('supporting-'+str(i),v) for i,v in enumerate(a.supporting_run)]+[('retained-failure-'+str(i),v) for i,v in enumerate(a.failed)]:
        r=directory(name);result=json.loads((r/'result.json').read_text(encoding='utf-8'))
        if result.get('recovery_passed') is not True:raise ValueError('Restoration not confirmed')
        passed=result.get('ui_automation',{}).get('passed') is True
        if not label.startswith('retained') and not passed:raise ValueError('Required trial failed')
        verdicts[label]=dict(directory=name,passed=passed,recovery_passed=True,physical_acceptance=False)
        with zipfile.ZipFile(r.with_name(r.name+'-safe.zip')) as z:
            if z.testzip():raise ValueError('Corrupt safe ZIP')
            for item in z.infolist():
                n=pathlib.PurePosixPath(item.filename)
                if n.is_absolute() or '..' in n.parts or '\\' in item.filename or item.file_size>8*1024*1024 or n.suffix.lower() in ('.raw','.cookie','.exe','.ttf','.ttc','.mp4','.mp3') or 'account' in item.filename.lower():raise ValueError('Private payload')
                files[label+'/'+item.filename]=z.read(item)
        if (r/'SCREENSHOTS.html').is_file():files[label+'/SCREENSHOTS.html']=(r/'SCREENSHOTS.html').read_bytes()
    for label,name in [('audit',a.audit),('units',a.units),('qt',a.qt),('account-readonly',a.account)]+[('retained-qt-failure-'+str(i),v) for i,v in enumerate(a.failed_qt)]:
        r=directory(name);result=json.loads((r/'result.json').read_text(encoding='utf-8'))
        if label=='units':
            if result.get('host_exit')!=0:raise ValueError('Unit checks failed')
            files[label+'/stderr.txt']=(r/'stderr.raw').read_bytes()
        elif not label.startswith('retained') and result.get('passed') is not True:raise ValueError('Required audit failed')
        if label=='audit' and result.get('active_private_processes')!=0:raise ValueError('Owned processes remain')
        files[label+'/result.json']=(r/'result.json').read_bytes()
        if label=='qt':
            for stem in result.get('captures',[]):
                if not isinstance(stem,str) or not __import__('re').fullmatch(r'[0-9]{2}-[a-z-]+',stem):raise ValueError('Capture not allowlisted')
                image=r/(stem+'.png')
                if image.is_symlink():raise ValueError('Symlink capture')
                files['synthetic-ui/'+stem+'.png']=image.read_bytes()
    report=ROOT/'04_Documents'/a.report
    if report.parent!=ROOT/'04_Documents' or not report.is_file():raise ValueError('Report scope')
    files['REPORT.md']=report.read_bytes();files['native-build-manifest.json']=(BASE/'out/strip-player.build.json').read_bytes()
    for name in ('TEST_BILI_EXPANDED.cmd','TEST_BILI_EXPANDED_AUTO.cmd'):files['entrypoints/'+name]=(BASE/name).read_bytes()
    for name in ('BiliP011-ExtraContracts-20260927-045734','BiliP011-OfficialFeatureSources-20260926-170412'):
        files['official-sources/'+name+'.json']=(directory(name)/'sources.json').read_bytes()
    files['README.txt']=('P011 Bili 扩展验证证据包\n\n'
        '先读 REPORT.md；catalog、features、regression 是最终候选的三次独立试验。\n'
        '各目录 SCREENSHOTS.html 可在解压后直接打开。synthetic-ui 为主机合成账号界面，不是实机账号截图。\n'
        'supporting-* 是此前通过的辅助证据，不累计到最终候选的检查数量；retained-* 保留失败，不改判。\n'
        'entrypoints 依赖原工作区、ADB 和不可变媒体目录，本包不能独立安装、刷写或恢复固件。\n'
        '没有真实账号写入/验证码/物理验收通过声明。旧切画质首帧超时仍未根治，完整项目尚未完成。\n'
        'MANIFEST.json 记录每个证据文件的 SHA-256。原始日志保留在用户本机，未纳入本包。\n').encode('utf-8')
    meta={'schema':1,'verdicts':verdicts,'account_writes_tested':False,'physical_acceptance':False,
        'default_media_changed':False,'not_interested_implemented':False,'full_cloud_sync':False,
        'known_quality_switch_timeout_resolved':False,'files':{n:hashlib.sha256(b).hexdigest() for n,b in sorted(files.items())}}
    files['MANIFEST.json']=json.dumps(meta,ensure_ascii=False,indent=2).encode('utf-8')
    files['PRIVACY.txt']=b'Public device captures and synthetic account UI only. No credentials, private account content, raw logs, signed stream URLs, media cache, firmware or fonts. Host/device/manual evidence are distinct. Retained failures remain failures.\n'
    out=ROOT/'logs'/('BiliP011-Expanded-Delivery-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-safe.zip')
    with zipfile.ZipFile(out,'x',zipfile.ZIP_DEFLATED) as z:
        for n,b in sorted(files.items()):z.writestr(n,b)
    with zipfile.ZipFile(out) as z:
        if z.testzip() or set(z.namelist())!=set(files):raise ValueError('ZIP integrity')
    print('SAFE_RESULT_ZIP='+str(out));print('ZIP_SHA256='+hashlib.sha256(out.read_bytes()).hexdigest());print('FILES='+str(len(files)))
if __name__=='__main__':main()
