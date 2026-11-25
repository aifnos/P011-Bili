"""Archive passed PC-only Qt fixture screenshots, never device or account data."""
import argparse,hashlib,html,json,pathlib,re,struct,zipfile
from test_client import service
from review_gallery import LABELS


def digest(body):return hashlib.sha256(body).hexdigest()


def exact_list(values,allowed):
    if not isinstance(values,list) or any(not isinstance(x,str) for x in values):
        raise ValueError('Invalid check/capture list')
    if len(values)!=len(allowed) or set(values)!=set(allowed):
        raise ValueError('Incomplete or unexpected check/capture list')
    return values


def regular(path,limit):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>limit:
        raise ValueError('Not a bounded regular fixture file')
    return path.read_bytes()


def collect(root):
    root=pathlib.Path(root)
    if root.is_symlink() or not root.is_dir() or not re.fullmatch(r'BiliP011-AutoQtQA-\d{8}-\d{6}',root.name):
        raise ValueError('Not a host automation run')
    if (root/'screenshots').is_symlink() or not (root/'screenshots').is_dir():
        raise ValueError('Not a screenshot directory')
    raw=regular(root/'result.json',1024*1024);result=json.loads(raw)
    if result.get('passed') is not True or result.get('layer')!='PC Qt with synthetic API only':
        raise ValueError('Not a passed PC fixture result')
    for name in ('device_tested','device_capture_backend_tested','audio_played','account_page_captured','physical_touch_verified'):
        if result.get(name) is not False:raise ValueError('Wrong evidence/privacy layer')
    if result.get('error')!='' or result.get('host_capture_error')!='' or result.get('warnings')!=[]:
        raise ValueError('Failed or warned host run')
    if result.get('host_capture_backend')!='QQuickItem.grabToImage':raise ValueError('Unexpected capture backend')
    checks=exact_list(result.get('checks'),service.UI_QA_CHECKS)
    toolbox=exact_list(result.get('toolbox_checks',[]),service.TOOLBOX_QA_CHECKS if result.get('toolbox_checks') else ())
    if toolbox and (result.get('lan_opened') is not False or result.get('isolated_user_files') is not True):
        raise ValueError('Wrong Toolbox fixture boundary')
    captures=exact_list(result.get('captures'),service.UI_QA_CAPTURES+(service.TOOLBOX_QA_CAPTURES if toolbox else ()))
    records=result.get('host_capture_records')
    if records!=[dict(name=name,width=800,height=480) for name in captures]:
        raise ValueError('Capture records differ')
    files={};index=[];cards=[]
    for name in captures:
        member='screenshots/'+name+'.png';body=regular(root/member,4*1024*1024)
        if len(body)<24 or body[:8]!=b'\x89PNG\r\n\x1a\n' or body[12:16]!=b'IHDR' or struct.unpack('>II',body[16:24])!=(800,480):
            raise ValueError('Wrong screenshot geometry')
        files[member]=body;index.append(dict(name=name,width=800,height=480,sha256=digest(body)))
        label='输入适配器 / PC 离线回退' if name=='16-input-component' else LABELS[name]
        cards.append('<figure><a href="'+member+'"><img loading="lazy" width="800" height="480" src="'+member+'" alt="'+html.escape(label)+'"></a><figcaption>'+html.escape(label)+'</figcaption></figure>')
    # Do not copy arbitrary API text, paths, logs, run-directory contents or
    # even the generic service's device-labelled ui-qa-result.json.
    safe=dict(passed=True,layer='PC Qt with synthetic API only',device_tested=False,
              device_capture_backend_tested=False,audio_played=False,physical_touch_verified=False,
              account_page_captured=False,lan_opened=False,checks=checks,toolbox_checks=toolbox,
              captures=captures,host_capture_backend='QQuickItem.grabToImage',warnings=[],
              qt515_compatibility_notice_count=len(result.get('qt515_compatibility_notices',[])),
              source_result_sha256=digest(raw),capture_index=index)
    files['result.safe.json']=json.dumps(safe,ensure_ascii=False,indent=2).encode('utf-8')
    heading='P011 · 电脑端 Qt 测试图集（非实机）'
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' file:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>'''+heading+'''</title><style>body{margin:0;background:#080f17;color:#edf5fa;font:16px system-ui,sans-serif}header,main{max-width:1640px;margin:auto;padding:24px}p{line-height:1.6;color:#b4cbd4}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,600px),1fr));gap:16px}figure{margin:0;background:#142330;border-radius:12px;overflow:hidden}img{display:block;width:100%;height:auto}figcaption{padding:12px}a{color:#66dccf}</style><header><h1>'''+heading+'</h1><p>Bili '+str(len(checks))+' 项 · 工具箱 '+str(len(toolbox))+' 项 · '+str(len(captures))+''' 张真实 Qt 渲染截图。</p><p>所有内容使用本地合成接口和隔离文件。不是新设备、登录、播放性能、声音或玻璃触摸验收。原厂键盘在 PC 无资源时走离线回退，不能用本图证明笔端原厂键盘。8K/HDR 等为布局测试档位，不是实际流或可播放证明。</p><p>原始图片 800×480，内容区 y=106、高 268；上下黑边属于测试窗体。未修图、缩放原文件或伪造缺失截图。只归档固定公开页面，不包含登录页、二维码、账号、原厂日志或任意运行目录文件。</p></header><main>'''+''.join(cards)+'</main></html>'
    files['HOST-SCREENSHOTS.html']=page.encode('utf-8')
    manifest={'layer':safe['layer'],'device_tested':False,'files':{name:dict(bytes=len(body),sha256=digest(body)) for name,body in sorted(files.items())}}
    files['HOST-UI-MANIFEST.json']=json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8')
    return files


def archive(root):
    root=pathlib.Path(root);files=collect(root)
    target=root.with_name(root.name+'-host-safe.zip');gallery=root/'HOST-SCREENSHOTS.html'
    if target.exists() or target.is_symlink() or gallery.exists() or gallery.is_symlink():
        raise ValueError('Refusing to replace an existing archive or gallery')
    with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED) as z:
        for name,body in files.items():z.writestr(name,body)
    with zipfile.ZipFile(target) as z:
        if z.testzip() is not None or set(z.namelist())!=set(files):raise ValueError('Archive verification failed')
        for name,body in files.items():
            if digest(z.read(name))!=digest(body):raise ValueError('Archive hash differs')
    with gallery.open('xb') as f:f.write(files['HOST-SCREENSHOTS.html'])
    print('HOST_UI_ZIP='+str(target));print('ZIP_SHA256='+digest(target.read_bytes()))
    print('HOST_UI_GALLERY='+str(gallery))
    return target


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=pathlib.Path)
    archive(parser.parse_args().directory)
