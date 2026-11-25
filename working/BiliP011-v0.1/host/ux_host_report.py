"""Whitelist-only host UX evidence package; no ADB, login or media cache."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import zipfile
BASE=Path(__file__).resolve().parents[1]
ROOT=BASE.parents[1]
PAGES=('01-recommendations','01b-home-swipe','04-search-input','04-offline-pinyin','05-search-results','05b-open-ready',
       '06-video-details','07-description','08-qualities','09-comments','10-comments-next',
       '10b-replies','10c-history','11-network-error','12-empty-state','13-permission-error','14-comments-error','15-input-error')
SOURCES=('BiliPanel.qml','BiliButton.qml','BiliInput.qml','BiliKeyboard.qml','BiliScrollHint.qml','BiliUx.js','library.py','stream_transaction.hpp','PlayerAutomation.qml','BiliAutomation.qml',
         'ToolboxAutomation.qml','service.py','story.py','story_cache.py','player.cpp','player_v2.cpp','player_gestures.hpp','cached_media.hpp',
         'media_prefetch.hpp','hardware_worker.cpp','hardware_picture.hpp')
GALLERY_PAGES=('toolbox-home','toolbox-files','toolbox-text','toolbox-image','toolbox-snake','toolbox-2048','toolbox-bricks',
               'toolbox-dashboard','toolbox-curves','toolbox-processes','01-recommendations','02-next-cards','03-video-details',
               '09-description','10-qualities','11-comments','12-comments-next','14-comment-replies','04-offline-keyboard',
               '05-search-input','06-search-results','07-bangumi','13-bangumi-details','15-bangumi-scrolled','08-input-error',
               '16-input-component','17-api-high-qualities')

def read(directory,name,cap=4*1024*1024):
    path=directory/name
    if path.is_symlink() or not path.is_file() or path.stat().st_size>cap:raise ValueError('Unexpected evidence file')
    return path.read_bytes()

def main():
    parser=argparse.ArgumentParser()
    for name in ('unit','build','preview','gallery'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    for name in ('unit','build','preview','gallery'):
        directory=getattr(args,name).resolve()
        if directory.parent!=(ROOT/'logs').resolve() or directory.is_symlink():raise ValueError('Not a local run')
        setattr(args,name,directory)
    unit=json.loads(read(args.unit,'result.json'));build=json.loads(read(args.build,'result.json'))
    preview=json.loads(read(args.preview,'result.json'));gallery=json.loads(read(args.gallery,'result.json'))
    if unit.get('host_exit')!=0 or build.get('host_exit')!=0 or not preview.get('passed') or not gallery.get('passed'):raise ValueError('Incomplete host evidence')
    from strip_player_artifact import validate_strip_player
    validate_strip_player(BASE)
    report=dict(passed=True,layer='host-only',device_tested=False,physical_touch_verified=False,
                player_transition_verified=False,live_cache_hit_verified=False,playback_performance_verified=False,
                default_promoted=False,permanent_install=False,unit_run=args.unit.name,native_build_run=args.build.name,
                preview_run=args.preview.name,gallery_run=args.gallery.name,qt_checks=preview['checks'],
                integration_checks=gallery['checks']+gallery['toolbox_checks'],
                source_sha256={'client/'+name:hashlib.sha256((BASE/'client'/name).read_bytes()).hexdigest() for name in SOURCES})
    files={'result.json':json.dumps(report,ensure_ascii=False,indent=2).encode('utf-8'),
           'host-tests.stderr.txt':read(args.unit,'stderr.raw'),
           'native-build.json':(BASE/'out/strip-player.build.json').read_bytes()}
    for name in PAGES:
        if (args.preview/(name+'.png')).is_file():files['screenshots/'+name+'.png']=read(args.preview,name+'.png')
    for name in GALLERY_PAGES:
        files['integration-screenshots/'+name+'.png']=read(args.gallery/'screenshots',name+'.png')
    files['SHA256.json']=json.dumps({n:hashlib.sha256(b).hexdigest() for n,b in files.items()},indent=2).encode('ascii')
    out=ROOT/'logs'/('BiliP011-UXHost-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-safe.zip')
    with zipfile.ZipFile(out,'x',zipfile.ZIP_DEFLATED) as archive:
        for name,body in files.items():archive.writestr(name,body)
    with zipfile.ZipFile(out) as archive:
        if archive.testzip() is not None or any(archive.read(n)!=b for n,b in files.items()):raise ValueError('Archive verification failed')
    print('HOST_ONLY_ZIP='+str(out));print('SHA256='+hashlib.sha256(out.read_bytes()).hexdigest())

if __name__=='__main__':main()
