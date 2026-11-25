"""Export only libraries we built, never the vendor link sysroot or fonts."""
import hashlib,json,pathlib,re,shutil,subprocess,sys
from build_deps import P,TRIPLE

files={}
names=['libmpv.so.2','libavcodec.so.60','libavformat.so.60','libavfilter.so.9',
       'libavutil.so.58','libswscale.so.7','libswresample.so.4','libass.so.9',
       'libfreetype.so.6','libharfbuzz.so.0','libfribidi.so.0',
       'libssl.so.3','libcrypto.so.3','libcurl.so.4','libdav1d.so.7']
for name in names:files['lib/'+name]=P/'lib'/name
if '--private-sdl' in sys.argv:
    if '--client' not in sys.argv or '--hardware' not in sys.argv or '--player-from' in sys.argv:
        raise ValueError('Private SDL requires its freshly built hardware player pair')
    sys.path.insert(0,'/src/host')
    from strip_player_artifact import validate_strip_player
    files['lib/libSDL2-2.0.so.0']=validate_strip_player(pathlib.Path('/src'))
if '--private-omx' in sys.argv:
    if '--private-sdl' not in sys.argv:raise ValueError('Private OMX requires its fresh strip/SDL pair')
    from strip_player_artifact import validate_bundled_omx
    files['lib/gst/libgstomx.so']=validate_bundled_omx(pathlib.Path('/src'))
elif '--private-sdl' in sys.argv and json.loads(pathlib.Path('/src/out/strip-player.build.json').read_text()).get('bundled_omx'):
    raise ValueError('Cannot omit required private OMX from this player')
for name in ('libstdc++.so.6','libgcc_s.so.1','libatomic.so.1'):
    files['lib/'+name]=pathlib.Path(subprocess.check_output([TRIPLE+'-g++','-print-file-name='+name],text=True).strip())
for name in ('mpv-probe','gles-probe','api-probe'):files['bin/'+name]=pathlib.Path('/src/out')/name
if '--client' in sys.argv:
    for name in ('bili-api','bili-player'): files['bin/'+name]=pathlib.Path('/src/out')/name
    if '--hardware' in sys.argv:files['bin/bili-hw']=pathlib.Path('/src/out/bili-hw')
    if '--player-from' in sys.argv:
        # API-only refreshes can retain a physically accepted immutable player.
        base=pathlib.Path(sys.argv[sys.argv.index('--player-from')+1]).resolve()
        raw_base=(base/'manifest.json').read_bytes()
        if base.parent!=pathlib.Path('/src/out') or base.name!='media-'+hashlib.sha256(raw_base).hexdigest()[:16]:raise ValueError('Invalid player base identity')
        player=base/'bin/bili-player';pinned=json.loads(raw_base)['bin/bili-player'];body=player.read_bytes()
        if len(body)!=pinned['bytes'] or hashlib.sha256(body).hexdigest()!=pinned['sha256']:raise ValueError('Player base differs')
        files['bin/bili-player']=player
        base_manifest=json.loads(raw_base)
        if ('bin/bili-hw' in base_manifest)!=('--hardware' in sys.argv):raise ValueError('Pinned player/backend pair differs')
        if '--hardware' in sys.argv:
            worker=base/'bin/bili-hw';pinned_worker=base_manifest['bin/bili-hw'];worker_body=worker.read_bytes()
            if len(worker_body)!=pinned_worker['bytes'] or hashlib.sha256(worker_body).hexdigest()!=pinned_worker['sha256']:raise ValueError('Pinned hardware backend differs')
            files['bin/bili-hw']=worker
        print('PINNED_PLAYER_SOURCE='+str(base))
files['bin/curl']=P/'bin/curl'
manifest={}
for name,path in sorted(files.items()):
    data=path.read_bytes()
    hdr=subprocess.check_output([TRIPLE+'-readelf','-h',path],text=True)
    if not re.search(r'Class:\s+ELF32',hdr) or not re.search(r'Machine:\s+ARM',hdr):raise ValueError('Not ARM32: '+name)
    version=subprocess.check_output([TRIPLE+'-readelf','-V',path],text=True)
    versions=set(re.findall(r'\bGLIBC_(\d+\.\d+(?:\.\d+)?)',version))
    if any(tuple(map(int,v.split('.')))>(2,27) for v in versions):raise ValueError('Too new glibc: '+name)
    dynamic=subprocess.check_output([TRIPLE+'-readelf','-d',path],text=True)
    manifest[name]={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),
                    'glibc':sorted(versions),'needed':re.findall(r'\(NEEDED\).*\[(.*?)\]',dynamic)}
raw=json.dumps(manifest,sort_keys=True,indent=2).encode()
identity=hashlib.sha256(raw).hexdigest()
out=pathlib.Path('/src/out')/('media-'+identity[:16]);out.mkdir(exist_ok=True)
for name,path in files.items():
    dest=out/name;dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest()!=manifest[name]['sha256']:raise ValueError('Export differs')
    if not dest.exists():shutil.copyfile(path,dest)
(out/'manifest.json').write_bytes(raw)
print('EXPORTED='+str(out));print('IDENTITY='+identity)
