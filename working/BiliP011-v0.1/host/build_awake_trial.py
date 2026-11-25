"""PC-only builder. Copies exact v2.4.0 UI, changes one compressed QML record.

Leading indentation is removed from the existing NaviPanel, without changing
tokens, strings, comments or line endings. All other resource/ELF bytes compare.
"""
import argparse
import ast
import hashlib
import json
import pathlib
import re
import secrets
import struct
import zlib

BASE = pathlib.Path(__file__).resolve().parents[1]
ROOT = BASE.parents[1]
NATIVE = ROOT / 'working/ToolboxNext-v0.5.1-native'
ORIGINAL = ROOT / '06_Firmware/backups/v2.4.0-20260923-162730/files/Z03'
PIN = 'cb8d6a78617d50f64c6adc8056427dd963bc83979cbb04e349275dd8e8ffb62a'


def client_bridge(bridge, remote):
    addition = '\nproperty var navigator:null\nTimer {interval:1200;running:true;onTriggered:{if(bridge.navigator){bridge.navigator.sceneSource="file://'+remote+'/BiliPanel.qml";console.log("P011_BILI SCENE_ENTERED");}}}\n'
    at=bridge.rfind('}')
    return bridge[:at]+addition+bridge[at:]


def build(media, client=False, automated=False, player_protocol=1, toolbox=False, soak_seconds=0, benchmark_quality=None, benchmark_bvid='BV1Da411Y7U4', benchmark_seek=False, benchmark_danmaku_delay=0, demo_seconds=0, ux_state=False, ux_probe=False, soak_bvid='',feature_probe=False,catalog_probe=False,screen_check=False,window_pose=None,story_probe=False):
    if automated and not client: raise ValueError('Automation requires client')
    if type(story_probe) is not bool or story_probe and (not(client and automated and player_protocol==2 and ux_state) or any((toolbox,soak_seconds,benchmark_quality is not None,demo_seconds,ux_probe,feature_probe,catalog_probe,screen_check,window_pose))):raise ValueError('Story probe requires isolated automated client')
    if window_pose is not None and (window_pose not in ('landscape','portrait') or not(client and automated and player_protocol==2 and ux_state and benchmark_quality==32 and benchmark_bvid=='BV1Da411Y7U4') or any((toolbox,soak_seconds,benchmark_seek,benchmark_danmaku_delay,demo_seconds,ux_probe,feature_probe,catalog_probe,screen_check))):raise ValueError('Window pose requires isolated fixed q32 benchmark')
    if type(screen_check) is not bool or screen_check and not(client and automated and player_protocol==2 and ux_state and toolbox and not ux_probe and not feature_probe and not catalog_probe and not soak_seconds and benchmark_quality is None and not demo_seconds):raise ValueError('Screen checks require explicit isolated full regression')
    if type(catalog_probe) is not bool or catalog_probe and not(client and automated and player_protocol==2 and ux_state and not toolbox and not ux_probe and not feature_probe and not soak_seconds and benchmark_quality is None and not demo_seconds):raise ValueError('Catalog probe requires isolated automated client')
    if type(feature_probe) is not bool or feature_probe and not(client and automated and player_protocol==2 and ux_state and not toolbox and not ux_probe and not soak_seconds and benchmark_quality is None and not demo_seconds):raise ValueError('Feature probe requires isolated explicit automated UX client')
    if type(ux_probe) is not bool or ux_probe and not(client and automated and player_protocol==2 and ux_state and not toolbox and not soak_seconds and benchmark_quality is None and not demo_seconds):raise ValueError('State probe requires isolated explicit automated UX client')
    if toolbox and not client:raise ValueError('Toolbox requires client')
    if player_protocol not in (1,2): raise ValueError('Unknown player protocol')
    if type(demo_seconds) is not int or demo_seconds not in (0,180):raise ValueError('Unknown demonstration duration')
    if demo_seconds and (not client or automated or player_protocol!=2 or toolbox or soak_seconds or benchmark_quality is not None):raise ValueError('Audible demonstration requires explicit isolated manual client')
    if type(soak_seconds) is not int or soak_seconds not in (0,130):raise ValueError('Unknown soak duration')
    if soak_seconds and not (client and automated and player_protocol==2):raise ValueError('Soak requires explicit protocol-2 automation')
    if not isinstance(soak_bvid,str) or soak_bvid and (not re.fullmatch('BV[0-9A-Za-z]{10}',soak_bvid) or not(client and automated and player_protocol==2 and soak_seconds==130)):raise ValueError('Fixed source requires explicit bounded automated soak')
    if benchmark_quality is not None and (type(benchmark_quality) is not int or not 1<=benchmark_quality<=65535 or not(client and automated and player_protocol==2) or soak_seconds):raise ValueError('Benchmark requires bounded explicit quality and protocol 2')
    if type(benchmark_seek) is not bool or benchmark_seek and benchmark_quality is None:raise ValueError('Seek probe requires an explicit benchmark')
    if type(benchmark_danmaku_delay) is not int or benchmark_danmaku_delay not in (0,8):raise ValueError('Unknown delayed-danmaku probe')
    if benchmark_danmaku_delay and (benchmark_quality not in (80,116) or benchmark_seek):raise ValueError('Delayed danmaku requires a fixed q80/q116 benchmark')
    if not isinstance(benchmark_bvid,str) or not re.fullmatch('BV[0-9A-Za-z]{10}',benchmark_bvid):raise ValueError('Invalid public benchmark ID')
    media = media.resolve()
    if type(ux_state) is not bool or ux_state and not(client and player_protocol==2):raise ValueError('UX state requires explicit protocol-2 client')
    if ux_state:
        from strip_player_artifact import validate_strip_player
        validate_strip_player(BASE)
        if hashlib.sha256((media/'bin/bili-player').read_bytes()).digest()!=hashlib.sha256((BASE/'out/bili-player').read_bytes()).digest():raise ValueError('UX state player differs from current verified build')
    raw_manifest = (media / 'manifest.json').read_bytes()
    media_id = hashlib.sha256(raw_manifest).hexdigest()
    if media.parent != BASE / 'out' or media.name != 'media-' + media_id[:16]: raise ValueError('Wrong media bundle')
    manifest = json.loads(raw_manifest)
    for name, meta in manifest.items():
        if name!='lib/gst/libgstomx.so' and not re.fullmatch(r'(bin|lib)/[A-Za-z0-9_.+-]+', name): raise ValueError('Unsafe media path')
        data = (media / name).read_bytes()
        if len(data) != meta['bytes'] or hashlib.sha256(data).hexdigest() != meta['sha256']: raise ValueError('Media differs')
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == PIN
    # Re-derive the new firmware's QRC offsets from its own register function.
    tree, names, data_at = [struct.unpack_from('<I', original, literal-0x10000)[0]+pc-0x10000 for literal,pc in ((0x36b40,0x36b30),(0x36b3c,0x36b2c),(0x36b38,0x36b24))]
    assert (tree, names, data_at) == (0x1a3acc, 0x1a5efc, 0x1a9f54)
    resources = {}; visited = set()
    def walk(index, parent):
        assert index not in visited and tree + index*22+22 <= names; visited.add(index)
        at = tree + index*22; no, flags = struct.unpack_from('>IH', original, at)
        pos = names + no; length = struct.unpack_from('>H', original, pos)[0]
        assert names <= pos and pos + 6 + length*2 <= data_at
        name = original[pos+6:pos+6+length*2].decode('utf-16-be'); path = parent+'/'+name if index else ''
        if flags & 2:
            count, first = struct.unpack_from('>II', original, at+6); assert count < 1000
            for child in range(first, first+count): walk(child, path)
        else:
            offset = data_at + struct.unpack_from('>I', original, at+10)[0]
            size = struct.unpack_from('>I', original, offset)[0]
            body = original[offset+4:offset+4+size]
            if flags & 1:
                size_raw = struct.unpack_from('>I', body)[0]; body = zlib.decompress(body[4:]); assert len(body) == size_raw
            resources[path] = (offset, size, flags, body)
    walk(0, ''); assert len(resources) == 400
    offset, size, flags, source = resources['/NaviPanel.qml']
    assert flags & 1 and offset == 1946708 and size == 1580
    session = secrets.token_hex(12); remote = '/mnt/data/p011-toolbox/bili-awake/' + session
    lines = source.decode('utf-8').splitlines(keepends=True)
    source_compact = ''.join(line.lstrip(' \t') for line in lines)
    loader = 'Loader { source: "file://' + remote + '/Bridge.qml"'+(';onLoaded:item.navigator=navi' if client else '')+' }\n'
    assert source_compact.count('id: navi\n') == 1
    qml = source_compact.replace('id: navi\n', 'id: navi\n' + loader, 1).encode('utf-8')
    packed = struct.pack('>I', len(qml)) + zlib.compress(qml, 9)
    if len(packed) > size: raise ValueError('QRC slot too small: %d > %d' % (len(packed), size))
    block = struct.pack('>I', len(packed)) + packed + bytes(size-len(packed))
    candidate = original[:offset] + block + original[offset+4+size:]
    assert len(candidate) == len(original) and candidate[:offset] == original[:offset] and candidate[offset+4+size:] == original[offset+4+size:]
    assert zlib.decompress(candidate[offset+8:offset+4+len(packed)]) == qml
    out = BASE / 'out' / ('awake-' + session); out.mkdir(exist_ok=False)
    files = {
        'Z03.awake-candidate': candidate,
        'Bridge.qml': (BASE/'bridge/Bridge.qml').read_text(encoding='utf-8').replace('@SESSION@', session).replace('@REMOTE@', remote).encode(),
        'awake_trial.py': (BASE/'runtime/awake_trial.py').read_bytes(),
        'native_safety.py': (NATIVE/'runtime/native_safety.py').read_bytes(),
        'p011_json.py': (NATIVE/'runtime/p011_json.py').read_bytes(),
    }
    config = dict(SESSION=session, REMOTE=remote, MEDIA='/mnt/data/p011-toolbox/bili-media/'+media_id[:16],
                  MEDIA_FILES={name: meta['sha256'] for name,meta in manifest.items()})
    if client:
        if not {'bin/bili-api','bin/bili-player'}.issubset(manifest): raise ValueError('Client runtime not built')
        config['CLIENT'] = True
        config['PLAYER_PROTOCOL'] = player_protocol
        config['UX_STATE'] = ux_state
        bridge = files['Bridge.qml'].decode()
        files['Bridge.qml'] = client_bridge(bridge,remote).encode()
        if toolbox:
            config['TOOLBOX']=True
            files['Bridge.qml']=files['Bridge.qml'].replace(b'/BiliPanel.qml',b'/ToolboxShell.qml')
            for name in ('ToolboxShell.qml','toolbox_runtime.py','audio_guard.py'):
                files[name]=(BASE/'client'/name).read_text(encoding='utf-8').replace('@REMOTE@',remote).encode()
            for path in sorted((NATIVE/'device').iterdir()):
                if path.suffix in ('.qml','.js'):files[path.name]=path.read_bytes()
            for name in ('server.py','storage.py','metrics.py','audio.py'):
                files['toolbox_server.py' if name=='server.py' else name]=(NATIVE/'runtime'/name).read_bytes()
            for name in ('index.html','transfer.js','transfer.css','favicon.svg'):
                files['toolbox-web-'+name]=(NATIVE/'web'/name).read_bytes()
        for name in ('BiliPanel.qml','BiliLibrary.qml','BiliExtras.qml','BiliCaptcha.qml','BiliPolicy.qml','BiliLabel.qml','BiliButton.qml','BiliKeyboard.qml','BiliInput.qml','BiliScrollHint.qml','BiliUx.js','library.py','service.py','account_features.py','media_actions.py','catalog_features.py','live_danmaku.py','danmaku.py','dm_delay_probe.py','story.py','story_cache.py','media_relay.py','playback_policy.py','smoke.py'):
            files[name] = (BASE/'client'/name).read_text(encoding='utf-8').replace('@REMOTE@',remote).encode()
        if automated:
            config['UI_AUTOMATION'] = True
            if toolbox:files['ToolboxAutomation.qml']=(BASE/'client/ToolboxAutomation.qml').read_bytes()
            files['BiliAutomation.qml'] = (BASE/'client/BiliAutomation.qml').read_text(encoding='utf-8').replace('@REMOTE@',remote).encode()
            if benchmark_quality is not None:
                config['BENCHMARK_QUALITY']=benchmark_quality
                if benchmark_danmaku_delay:config['BENCHMARK_DANMAKU_DELAY']=benchmark_danmaku_delay
                files['BiliAutomation.qml']=(BASE/'client/BiliPerformance.qml').read_text(encoding='utf-8').replace('@BENCHMARK_QUALITY@',str(benchmark_quality)).replace('@BENCHMARK_BVID@',benchmark_bvid).encode()
                if window_pose:files['BiliAutomation.qml']=files['BiliAutomation.qml'].replace(b'property string windowPose:""',('property string windowPose:"'+window_pose+'"').encode())
                if benchmark_seek:
                    config['BENCHMARK_SEEK']=True
                    files['BiliAutomation.qml']=files['BiliAutomation.qml'].replace(b'property bool seekProbe:false',b'property bool seekProbe:true')
            if player_protocol==2:
                files['BiliAutomation.qml']=files['BiliAutomation.qml'].replace(b'property bool enhanced: false',b'property bool enhanced: true')
                files['PlayerAutomation.qml']=(BASE/'client/PlayerAutomation.qml').read_bytes()
                if 'bin/bili-hw' in manifest:files['PlayerAutomation.qml']=files['PlayerAutomation.qml'].replace(b'property bool hardwareRequired: false',b'property bool hardwareRequired: true')
                if ux_state:files['PlayerAutomation.qml']=files['PlayerAutomation.qml'].replace(b'property bool uxState: false',b'property bool uxState: true')
                if screen_check:files['PlayerAutomation.qml']=files['PlayerAutomation.qml'].replace(b'property int screenHoldMs: 0',b'property int screenHoldMs: 12000')
                if soak_seconds:
                    files['PlayerAutomation.qml']=files['PlayerAutomation.qml'].replace(b'property int soakSeconds: 0',('property int soakSeconds: '+str(soak_seconds)).encode())
                if soak_bvid:files['PlayerAutomation.qml']=files['PlayerAutomation.qml'].replace(b'property string soakBvid: ""',('property string soakBvid: "'+soak_bvid+'"').encode())
            if ux_probe:
                config['UX_PROBE']=True
                files['ux_probe.py']=(BASE/'client/ux_probe.py').read_bytes()
                files['BiliAutomation.qml']=(BASE/'client/BiliStateAutomation.qml').read_bytes()
            if feature_probe:
                if ux_probe or not client or player_protocol!=2 or toolbox:raise ValueError('Isolated feature probe only')
                config['FEATURE_PROBE']=True
                files['feature_probe.py']=(BASE/'client/feature_probe.py').read_bytes()
                files['BiliAutomation.qml']=(BASE/'client/BiliFeatureAutomation.qml').read_text(encoding='utf-8').replace('@REMOTE@',remote).encode()
            if catalog_probe:
                config['CATALOG_PROBE']=True
                files['catalog_probe.py']=(BASE/'client/catalog_probe.py').read_bytes()
                files['BiliAutomation.qml']=(BASE/'client/BiliCatalogAutomation.qml').read_text(encoding='utf-8').replace('@REMOTE@',remote).encode()
            if story_probe:
                config['STORY_PROBE']=True
                files['story_probe.py']=(BASE/'client/story_probe.py').read_bytes()
                files['BiliAutomation.qml']=(BASE/'client/BiliStoryAutomation.qml').read_text(encoding='utf-8').replace('@REMOTE@',remote).encode()
            qml_panel = files['BiliPanel.qml'].decode('utf-8')
            at = qml_panel.rfind('}')
            addition = '\nLoader { source: "BiliAutomation.qml"; onLoaded: item.target = panel }\n'
            files['BiliPanel.qml'] = (qml_panel[:at]+addition+qml_panel[at:]).encode('utf-8')
        if demo_seconds:
            files['BiliWatchDemo.qml']=(BASE/'client/BiliWatchDemo.qml').read_text(encoding='utf-8').replace('@DEMO_SECONDS@',str(demo_seconds)).encode()
            qml_panel=files['BiliPanel.qml'].decode('utf-8');at=qml_panel.rfind('}')
            addition='\nLoader { source: "BiliWatchDemo.qml"; onLoaded: item.target = panel }\n'
            files['BiliPanel.qml']=(qml_panel[:at]+addition+qml_panel[at:]).encode()
        files['minhttp.py'] = (NATIVE/'runtime/minhttp.py').read_bytes()
        files['stdlib-json35.zip'] = (BASE/'client/deps/stdlib-json35.zip').read_bytes()
        files['pinyin.json.z'] = (BASE/'client/deps/pinyin.json.z').read_bytes()
        files['PINYIN-LICENSE.txt'] = (BASE/'client/deps/rime-pinyin-simp/LICENSE').read_bytes()
        files['PINYIN-AUTHORS.txt'] = (BASE/'client/deps/rime-pinyin-simp/AUTHORS').read_bytes()
    files['config.py'] = ''.join(key+' = '+repr(value)+'\n' for key,value in config.items()).encode()
    for name, content in files.items():
        if name.endswith('.py'): ast.parse(content.decode('utf-8-sig'), feature_version=(3,5))
        (out/name).write_bytes(content)
    hashes = ''.join(hashlib.sha256(content).hexdigest()+' '+str(len(content))+' '+name+'\n' for name,content in sorted(files.items())).encode()
    (out/'SOURCE.sha256').write_bytes(hashes)
    result = dict(session=session, remote=remote, media_local=str(media), media_remote=config['MEDIA'],
                  original_sha256=PIN, candidate_sha256=hashlib.sha256(candidate).hexdigest(),
                  manifest_sha256=hashlib.sha256(hashes).hexdigest(), changed_resource='/NaviPanel.qml',
                  resources_verified=400, other_resources_unchanged=399, record_offset=offset,
                  slot_bytes=size, used_bytes=len(packed), device_tested=False)
    if client: result.update(client_adapter='v0.2',player_protocol=player_protocol)
    if ux_state:result['ux_state']=True
    if screen_check:result['screen_check']=True
    if window_pose:result['window_pose']=window_pose
    if ux_probe:result['ux_probe']=True
    if feature_probe:result['feature_probe']=True
    if catalog_probe:result['catalog_probe']=True
    if story_probe:result['story_probe']=True
    if automated: result['ui_automation'] = True
    if soak_seconds:result['soak_seconds']=soak_seconds
    if soak_bvid:result['soak_bvid']=soak_bvid
    if benchmark_quality is not None:result.update(benchmark_quality=benchmark_quality,benchmark_bvid=benchmark_bvid,benchmark_capture_policy='seek_probe' if benchmark_seek else 'paused_only')
    if benchmark_seek:result['benchmark_seek']=True
    if benchmark_danmaku_delay:result['benchmark_danmaku_delay']=benchmark_danmaku_delay
    if toolbox:result['toolbox'] = True
    if demo_seconds:result['watch_demo_seconds']=demo_seconds
    (out/'build-result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    (out/'NaviPanel.embedded.qml').write_bytes(qml)
    print(json.dumps(result, indent=2)); print('BUNDLE='+str(out))
    return out


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--media', type=pathlib.Path, required=True)
    parser.add_argument('--client',action='store_true')
    parser.add_argument('--automated',action='store_true')
    parser.add_argument('--player-protocol',type=int,choices=(1,2),default=1)
    parser.add_argument('--toolbox',action='store_true')
    parser.add_argument('--soak-seconds',type=int,choices=(0,130),default=0)
    args=parser.parse_args();build(args.media,args.client,args.automated,args.player_protocol,args.toolbox,args.soak_seconds)
