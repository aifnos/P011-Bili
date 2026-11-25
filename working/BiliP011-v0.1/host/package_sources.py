"""Source-only review ZIP. Explicit roots, no private runtime/log directories."""
import argparse,datetime,hashlib,json,pathlib,urllib.request,zipfile

BASE=pathlib.Path(__file__).resolve().parents[1]
ROOT=BASE.parents[1]
NATIVE=ROOT/'working/ToolboxNext-v0.5.1-native'
SUFFIXES={'.py','.qml','.js','.c','.cpp','.hpp','.h','.md','.cmd','.ps1','.json','.yaml','.html','.css','.svg','.ini','.cmake','.z','.zip','.txt','.sh'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--dependency-sources',type=pathlib.Path,required=True)
    p.add_argument('--cache-artifact',type=pathlib.Path)
    p.add_argument('--cached-worker-artifact',type=pathlib.Path)
    p.add_argument('--output-cache-artifact',type=pathlib.Path);a=p.parse_args()
    deps=a.dependency_sources.resolve()
    if deps.parent!=BASE/'out' or not deps.name.startswith('dependency-sources-'):raise ValueError('Not a local source export')
    with zipfile.ZipFile(deps) as z:
        manifest=json.loads(z.read('source-manifest.json'))
        if manifest.get('runtime_binaries_included') is not False or manifest.get('vendor_files_included') is not False:raise ValueError('Invalid source boundary')
        assert z.testzip() is None
    files={}
    def add(path,name):
        if not path.is_file() or path.is_symlink():raise ValueError('Not a regular source file')
        if name in files:raise ValueError('Duplicate source name')
        files[name]=path.read_bytes()
    def tree(path,prefix):
        for f in sorted(path.rglob('*')):
            if f.is_file() and not f.is_symlink() and '__pycache__' not in f.parts and '.git' not in f.parts and (f.suffix.lower() in SUFFIXES or f.name in ('Dockerfile','LICENSE','AUTHORS','COPYING')):
                add(f,prefix+'/'+f.relative_to(path).as_posix())
    for name in ('client','bridge','runtime','host','build','probes'):
        if (BASE/name).is_dir():tree(BASE/name,'BiliP011/'+name)
    if a.cache_artifact:
        from cache_artifact import validate
        artifact=a.cache_artifact.resolve();meta=validate(BASE,artifact)
        for name in meta['modified_open_source']:
            add(artifact/'modified-open-source'/name,'cache-diagnostic/modified-open-source/'+name)
        add(artifact/'build.json','cache-diagnostic/build.json')
    if a.cached_worker_artifact:
        from cached_worker_artifact import validate as validate_worker
        artifact=a.cached_worker_artifact.resolve();meta=validate_worker(BASE,artifact)
        for name in meta['modified_open_source']:
            add(artifact/'modified-open-source'/name,'cached-worker-diagnostic/modified-open-source/'+name)
        add(artifact/'build.json','cached-worker-diagnostic/build.json')
    if a.output_cache_artifact:
        from output_cache_artifact import validate as validate_output
        artifact=a.output_cache_artifact.resolve();_,meta=validate_output(BASE,artifact)
        for name in meta['modified_open_source']:
            add(artifact/'modified-open-source'/name,'output-cache-bundle/modified-open-source/'+name)
        add(artifact/'build.json','output-cache-bundle/build.json')
    # Carry the actual altered SDL and OMX, including configure/.in/.m/.S files that
    # the generic project suffix list intentionally omits. Never substitute
    # the unmodified upstream archive for the library's corresponding source.
    for private_name in ('SDL2-2.0.8-p011','gst-omx-1.14.2-p011'):
        private_tree=BASE/'third_party'/private_name
        if not private_tree.is_dir():continue
        forbidden={'.ttf','.ttc','.otf','.otc','.woff','.woff2','.pfa','.pfb','.pcf','.bdf','.dfont','.sfd','.fon','.fnt',
                   '.o','.a','.so','.dll','.exe','.pyc','.zip','.gz','.bz2','.xz','.tgz'}
        for path in sorted(private_tree.rglob('*')):
            if not path.is_file() or path.is_symlink() or '__pycache__' in path.parts or '.git' in path.parts:continue
            if path.suffix.lower() in forbidden:continue
            body=path.read_bytes()
            if body[:4] in (b'\x7fELF',b'\x00\x01\x00\x00',b'OTTO',b'ttcf',b'wOFF',b'wOF2'):continue
            add(path,'BiliP011/third_party/'+private_name+'/'+path.relative_to(private_tree).as_posix())
    for f in sorted(BASE.iterdir()):
        if f.is_file() and f.suffix in ('.md','.cmd','.json'):add(f,'BiliP011/'+f.name)
    for name in ('device','runtime','web','host'):
        if (NATIVE/name).is_dir():tree(NATIVE/name,'ToolboxNext/'+name)
    for name in ('README.md','INTEGRATION.md'):
        add(NATIVE/name,'ToolboxNext/'+name)
    upstream=BASE/'wiliwili'
    for src,dest in (
        ('LICENSE','LICENSE-GPL-3.0.txt'),
        ('library/QR-Code-generator/cpp/qrcodegen.hpp','QR-Code-generator/qrcodegen.hpp'),
        ('library/QR-Code-generator/cpp/qrcodegen.cpp','QR-Code-generator/qrcodegen.cpp'),
        ('library/borealis/library/include/borealis/extern/nlohmann/json.hpp','nlohmann/json.hpp'),
        ('library/borealis/library/lib/extern/glfw/deps/stb_image_write.h','stb/stb_image_write.h'),
        ('library/borealis/library/lib/extern/SDL/include/SDL_config_minimal.h','SDL/SDL_config_minimal.h'),
        ('library/borealis/library/lib/extern/SDL/LICENSE.txt','SDL/LICENSE.txt')):
        add(upstream/src,'third-party/'+dest)
    url='https://raw.githubusercontent.com/nlohmann/json/v3.11.2/LICENSE.MIT'
    with urllib.request.urlopen(url,timeout=30) as response:license_body=response.read(32769)
    if len(license_body)>32768 or b'Niels Lohmann' not in license_body or b'Permission is hereby granted' not in license_body:raise ValueError('Unexpected upstream notice')
    files['third-party/nlohmann/LICENSE.MIT']=license_body
    files['third-party/nlohmann/notice-source.json']=json.dumps({'url':url,'sha256':hashlib.sha256(license_body).hexdigest()},indent=2).encode()
    for name in ('P011-Bili增强播放器与工具箱集成-20260924.md','P011-Bili最终验收清单-20260924.md','P011-Bili目标完成审计-20260924.md','P011-Bili弹幕Story编码修正-20260924.md','P011-Bili性能与原厂组件复用-20260924.md','P011-Bili硬解后端与性能对照-20260924.md','P011-Bili显示缓冲与开源对照-20260925.md'):
        path=ROOT/'04_Documents'/name
        if path.is_file():add(path,'reports/'+name)
    add(deps,'third-party/'+deps.name)
    for name,body in files.items():
        if name.endswith(('.ttf','.otf','.ttc','.woff','.woff2')) or body[:4]==b'\x7fELF':raise ValueError('Font or runtime binary would be archived')
    record={'source_only':True,'factory_binaries_included':False,'credentials_included':False,
            'upstream_revision':'88e5876bea9502d06f46a8656e3530684d3aaf7d',
            'files':{name:{'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()} for name,body in sorted(files.items())}}
    out=ROOT/'packages'/('P011-Bili-SourceReview-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.zip');out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name,body in sorted(files.items()):z.writestr(name,body,compress_type=zipfile.ZIP_STORED if name.endswith('.zip') else zipfile.ZIP_DEFLATED)
        z.writestr('SOURCE-MANIFEST.json',json.dumps(record,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(out) as z:
        assert z.testzip() is None
        for name,meta in record['files'].items():assert hashlib.sha256(z.read(name)).hexdigest()==meta['sha256']
    print('SOURCE_REVIEW_ZIP='+str(out));print('FILES='+str(len(files)));print('SHA256='+hashlib.sha256(out.read_bytes()).hexdigest())

if __name__=='__main__':main()
