"""PC-only private installer payload builder; never opens ADB or target code.

Only the pinned v2.4.0 SetUserReport QRC record changes. The original Z03 is
read from its local private backup, never copied into a public source package.
"""
import argparse
import ast
import hashlib
import json
import pathlib
import re
import struct
import zlib

BASE = pathlib.Path(__file__).resolve().parents[2]
FORMAL = BASE / 'formal'
PROJECT = BASE.parents[1]
NATIVE = PROJECT / 'working/ToolboxNext-v0.5.1-native'
ORIGINAL = PROJECT / '06_Firmware/backups/v2.4.0-20260923-162730/files/Z03'
PIN = 'cb8d6a78617d50f64c6adc8056427dd963bc83979cbb04e349275dd8e8ffb62a'
MEDIA = BASE / 'out/media-6d99b414a032ec70'
RESOURCE = '/ZybQmlFiles/ZybSet/SetUserReport.qml'
SET_MAIN = '/ZybQmlFiles/ZybSet/SetMainPage.qml'
SET_MAIN_PIN = 'd8b200e4d31b077f264b551eda55de975957476c4acb978ef4c55e21fb3748b3'
RESOURCE_PIN = 'b6111a1515c8b1392845a2b7fc58028582cea0a20a7bcae2c977c3f0f338e7d1'
QRC_TREE, QRC_NAMES, QRC_DATA = 0x1a3acc, 0x1a5efc, 0x1a9f54
CLIENT_FILES = (
    'BiliPanel.qml', 'BiliLibrary.qml', 'BiliExtras.qml', 'BiliCaptcha.qml',
    'BiliPolicy.qml', 'BiliLabel.qml', 'BiliButton.qml', 'BiliKeyboard.qml',
    'BiliInput.qml', 'BiliScrollHint.qml', 'BiliUx.js', 'library.py', 'service.py',
    'account_features.py', 'media_actions.py', 'catalog_features.py',
    'live_danmaku.py', 'danmaku.py', 'dm_delay_probe.py', 'story.py',
    'story_cache.py', 'media_relay.py', 'playback_policy.py', 'smoke.py')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(',', ':')).encode('ascii')


def read_file(path):
    path = pathlib.Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected an existing regular source file: ' + str(path))
    return path.read_bytes()


def resource_map(binary):
    """Decode every resource with its exact fixed record and expanded bytes."""
    rows = {}
    seen = set()
    def walk(index, parent):
        if index in seen or index < 0 or QRC_TREE + index*22 + 22 > QRC_NAMES:
            raise ValueError('Invalid QRC tree')
        seen.add(index)
        at = QRC_TREE + index*22
        no, flags = struct.unpack_from('>IH', binary, at)
        pos = QRC_NAMES + no
        length = struct.unpack_from('>H', binary, pos)[0]
        if not QRC_NAMES <= pos < pos + 6 + length*2 <= QRC_DATA:
            raise ValueError('Invalid QRC name')
        name = binary[pos+6:pos+6+length*2].decode('utf-16-be')
        path = parent + '/' + name if index else ''
        if flags & 2:
            count, first = struct.unpack_from('>II', binary, at+6)
            if count > 1000:
                raise ValueError('Invalid QRC child count')
            for child in range(first, first+count):
                walk(child, path)
        else:
            offset = QRC_DATA + struct.unpack_from('>I', binary, at+10)[0]
            size = struct.unpack_from('>I', binary, offset)[0]
            raw = binary[offset+4:offset+4+size]
            if len(raw) != size:
                raise ValueError('Truncated resource')
            if flags & 1:
                decoder = zlib.decompressobj()
                body = decoder.decompress(raw[4:]) + decoder.flush()
                if (not decoder.eof or decoder.unused_data or decoder.unconsumed_tail or
                        len(body) != struct.unpack_from('>I', raw)[0]):
                    raise ValueError('Invalid compressed resource')
            else:
                body = raw
            if path in rows:
                raise ValueError('Duplicate resource')
            rows[path] = dict(offset=offset, size=size, flags=flags, body=body)
    walk(0, '')
    if len(rows) != 400:
        raise ValueError('Unexpected resource count')
    return rows


def feedback_wrapper(release_id):
    if not re.fullmatch('[0-9a-f]{24}', release_id):
        raise ValueError('Invalid release identity')
    source = ('file:///mnt/data/p011-toolbox/bili-formal/releases/' +
              release_id + '/app/FeedbackEntry.qml')
    return ('''// SPDX-License-Identifier: GPL-3.0-or-later
import QtQuick 2.7
import "qrc:/ZybQmlFiles/Funcs/UILogics.js" as UILogic
Rectangle {
id: feedback
anchors.fill: parent
color: "#16171b"
property string pageType: "p011BiliPage"
Loader { id: content; anchors.fill: parent; source: "%s" }
Text { anchors.centerIn: parent; color: "white"; font.pixelSize: 24;
text: "B 站程序暂不可用，请返回设置"; visible: content.status === Loader.Error }
Rectangle { x:12; y:8; width:120; height:48; color:"#36383e";
visible:content.status === Loader.Error
Text { anchors.centerIn:parent; text:"返回设置"; color:"white"; font.pixelSize:22 }
MouseArea { anchors.fill:parent; onClicked:UILogic.backToSetPage() }
}
}
''' % source).encode('utf-8')


def patch_z03(original, release_id):
    if sha(original) != PIN:
        raise ValueError('Z03 differs from pinned v2.4.0 backup')
    before = resource_map(original)
    target = before[RESOURCE]
    if (target['offset'], target['size'], target['flags']) != (0x22a578, 3183, 1):
        raise ValueError('Feedback QRC slot differs')
    if sha(target['body']) != RESOURCE_PIN or sha(before[SET_MAIN]['body']) != SET_MAIN_PIN:
        raise ValueError('Stock settings resources differ')
    qml = feedback_wrapper(release_id)
    packed = struct.pack('>I', len(qml)) + zlib.compress(qml, 9)
    if len(packed) > target['size']:
        raise ValueError('Feedback QML exceeds its fixed resource slot')
    offset, slot = target['offset'], target['size']
    block = struct.pack('>I', len(packed)) + packed + bytes(slot-len(packed))
    candidate = original[:offset] + block + original[offset+4+slot:]
    after = resource_map(candidate)
    changed = [p for p in before if before[p]['body'] != after[p]['body']]
    if changed != [RESOURCE] or len(candidate) != len(original):
        raise ValueError('Unexpected resource changes')
    if original[:offset] != candidate[:offset] or original[offset+4+slot:] != candidate[offset+4+slot:]:
        raise ValueError('Bytes outside feedback resource changed')
    if before[SET_MAIN] != after[SET_MAIN]:
        raise ValueError('Stock settings entry changed')
    return candidate, dict(changed_resource=RESOURCE, resources_verified=400,
                          other_resources_unchanged=399, record_offset=offset,
                          slot_bytes=slot, used_bytes=len(packed),
                          set_main_sha256=SET_MAIN_PIN,
                          outside_resource_record_unchanged=True,
                          elf_headers_and_executable_code_unchanged=True)


def patch_panel(data):
    text = data.decode('utf-8')
    old = '''    function quitTrial() {
        leaveLogin(); message="正在退出并恢复原厂界面…";
        http("POST","/exit",{},function(reply){exitRequested();},false);
    }'''
    new = '''    property bool formalExitSent: false
    property bool formalExitNotified: false
    function notifyFormalExit() {
        if (formalExitNotified) return;
        formalExitNotified = true;
        formalExitTimeout.stop();
        exitRequested();
    }
    function closeFormal(notify) {
        if (formalExitSent) {
            if (notify) notifyFormalExit();
            return;
        }
        formalExitSent = true;
        leaveLogin();
        if (notify) formalExitTimeout.restart();
        if (token !== "" && endpoint !== "") {
            var xhr = new XMLHttpRequest();
            xhr.onreadystatechange = function() {
                if (xhr.readyState === XMLHttpRequest.DONE && notify && !disposed)
                    notifyFormalExit();
            };
            xhr.open("POST", endpoint + "/exit");
            xhr.setRequestHeader("X-P011-Token", token);
            xhr.setRequestHeader("Content-Type", "application/json");
            xhr.send("{}");
        } else if (notify) notifyFormalExit();
    }
    function quitTrial() {
        closeFormal(true);
    }
    Timer { id:formalExitTimeout; interval:1500; onTriggered:panel.notifyFormalExit() }
    Timer {
        interval:1000; repeat:true
        running:panel.token!==""&&!panel.disposed&&!panel.formalExitSent
        onTriggered:panel.http("POST","/formal/heartbeat",{},function(reply){},false)
    }'''
    if text.count(old) != 1:
        raise ValueError('Bili exit source changed; review formal adaptation')
    text = text.replace(old, new, 1)
    hook = '        console.log("P011_BILI UI_DESTROYED");'
    if text.count(hook) != 1:
        raise ValueError('Bili destruction source changed')
    return text.replace(hook, '        closeFormal();\n'+hook, 1).encode('utf-8')


def patch_bridge(data):
    text = data.decode('utf-8')
    old = '''        // Independent 10 minute cap, even if the player leaves a fresh file.
        if (ticks >= 1200) { release(false); heartbeat.stop(); return; }
'''
    initial = '''        // Initial repeats cover the vendor socket connecting asynchronously.
        if (ticks <= 12 && ticks % 2 === 0) release(true);
'''
    completed = 'Component.onCompleted: { release(true); console.log("P011_AWAKE READY"); }'
    for needle in (old, initial, completed):
        if text.count(needle) != 1:
            raise ValueError('Awake bridge source changed; review formal adaptation')
    return text.replace(old, '', 1).replace(initial, '', 1).replace(
        completed, 'Component.onCompleted: { console.log("P011_AWAKE READY"); }', 1).encode('utf-8')


def source_inputs(native_dir):
    sources = {}
    for name in CLIENT_FILES:
        sources['client/'+name] = read_file(BASE/'client'/name)
    for name, path in (
        ('runtime/FeedbackEntry.qml', FORMAL/'runtime/FeedbackEntry.qml'),
        ('runtime/formal_service.py', FORMAL/'runtime/formal_service.py'),
        ('bridge/Bridge.qml', BASE/'bridge/Bridge.qml'),
        ('host/build_formal.py', pathlib.Path(__file__)),
        ('native_safety.py', NATIVE/'runtime/native_safety.py'),
        ('p011_json.py', NATIVE/'runtime/p011_json.py'),
        ('minhttp.py', NATIVE/'runtime/minhttp.py'),
        ('deps/stdlib-json35.zip', BASE/'client/deps/stdlib-json35.zip'),
        ('deps/pinyin.json.z', BASE/'client/deps/pinyin.json.z'),
        ('notices/THIRD_PARTY_NOTICES.md', BASE/'THIRD_PARTY_NOTICES.md'),
        ('notices/PINYIN-LICENSE.txt', BASE/'client/deps/rime-pinyin-simp/LICENSE'),
        ('notices/PINYIN-AUTHORS.txt', BASE/'client/deps/rime-pinyin-simp/AUTHORS'),
        ('notices/GPL-3.0.txt', BASE/'wiliwili/LICENSE')):
        sources[name] = read_file(path)
    native_meta_raw = read_file(native_dir/'build-result.json')
    native_meta = json.loads(native_meta_raw)
    if (native_meta.get('formal_runtime') is not True or
            native_meta.get('playback_limit_seconds') != 86400 or
            native_meta.get('device_tested') is not False or
            not native_meta.get('source_files')):
        raise ValueError('Native output lacks formal-runtime/source provenance')
    sources['native/build-result.json'] = native_meta_raw
    artifacts = native_meta.get('artifacts', {})
    for name in ('bin/bili-player', 'bin/bili-hw'):
        content = read_file(native_dir/name)
        if (len(content) < 52 or content[:6] != b'\x7fELF\x01\x01' or
                struct.unpack_from('<H', content, 18)[0] != 40):
            raise ValueError('Formal native output is not ELF32 ARM: '+name)
        expected = artifacts.get(name, {})
        if expected.get('sha256') != sha(content) or expected.get('bytes') != len(content):
            raise ValueError('Formal native artifact differs from provenance: '+name)
        sources['native/'+name] = content
    media_raw = read_file(MEDIA/'manifest.json')
    if sha(media_raw)[:16] != '6d99b414a032ec70':
        raise ValueError('Latest accepted media identity differs')
    media_meta = json.loads(media_raw)
    sources['media/manifest.json'] = media_raw
    for name, expected in media_meta.items():
        if not (re.fullmatch(r'(bin|lib)/[A-Za-z0-9_.+-]+', name) or name == 'lib/gst/libgstomx.so'):
            raise ValueError('Unsafe media member')
        content = read_file(MEDIA/name)
        if sha(content) != expected['sha256'] or len(content) != expected['bytes']:
            raise ValueError('Accepted media was modified: '+name)
        sources['media/'+name] = content
    return sources


def build(native_dir, output):
    native_dir, output = pathlib.Path(native_dir).resolve(), pathlib.Path(output).resolve()
    if output.exists():
        raise ValueError('Output must be a new directory; existing releases are immutable')
    sources = source_inputs(native_dir)
    source_manifest = {name: dict(sha256=sha(content), bytes=len(content))
                       for name, content in sorted(sources.items())}
    source_manifest['original-Z03-identity'] = dict(sha256=PIN, private_local_backup=True)
    identity = sha(canonical(source_manifest))
    release_id = identity[:24]
    state_remote = '/mnt/data/p011-toolbox/bili-awake/'+release_id
    release_remote = '/mnt/data/p011-toolbox/bili-formal/releases/'+release_id
    app_remote = release_remote+'/app'
    media_remote = release_remote+'/media'
    files = {}
    for name in CLIENT_FILES:
        content = sources['client/'+name]
        if name == 'BiliPanel.qml':
            content = patch_panel(content)
        if name == 'service.py':
            old = b'min(480, int(self.deadline-time.monotonic()-5))'
            if content.count(old) != 1:
                raise ValueError('Player duration source changed')
            content = content.replace(old, b'min(86400, int(self.deadline-time.monotonic()-5))', 1)
        files['app/'+name] = content.replace(b'@REMOTE@', state_remote.encode('ascii'))
    files['app/FeedbackEntry.qml'] = sources['runtime/FeedbackEntry.qml']
    files['app/formal_service.py'] = sources['runtime/formal_service.py']
    files['app/Bridge.qml'] = patch_bridge(sources['bridge/Bridge.qml']).replace(
        b'@REMOTE@', state_remote.encode('ascii')).replace(b'@SESSION@', release_id.encode('ascii'))
    for name in ('native_safety.py', 'p011_json.py', 'minhttp.py'):
        files['app/'+name] = sources[name]
    for name in ('stdlib-json35.zip', 'pinyin.json.z'):
        files['app/'+name] = sources['deps/'+name]
    for name in ('THIRD_PARTY_NOTICES.md', 'PINYIN-LICENSE.txt', 'PINYIN-AUTHORS.txt', 'GPL-3.0.txt'):
        files['app/'+name] = sources['notices/'+name]
    files['app/native-build-result.json'] = sources['native/build-result.json']
    media_manifest = {}
    for name, content in sources.items():
        if name.startswith('media/') and name != 'media/manifest.json':
            relative = name[6:]
            content = sources.get('native/'+relative, content)
            files[name] = content
            media_manifest[relative] = dict(sha256=sha(content), bytes=len(content))
    files['media/manifest.json'] = canonical(media_manifest)
    config = dict(SESSION=release_id, REMOTE=state_remote, APP=app_remote, MEDIA=media_remote,
                  MEDIA_FILES={name: info['sha256'] for name, info in media_manifest.items()},
                  CLIENT=True, PLAYER_PROTOCOL=2, UX_STATE=True, FORMAL_INSTALL=True,
                  UI_AUTOMATION=False)
    files['app/config.py'] = ''.join(key+' = '+repr(value)+'\n' for key, value in config.items()).encode('ascii')
    original = read_file(ORIGINAL)
    candidate, evidence = patch_z03(original, release_id)
    files['Z03.patched'] = candidate
    files['source-manifest.json'] = canonical(source_manifest)
    files['app/formal-adaptations.json'] = canonical(dict(
        service_playback_limit_before=480, service_playback_limit_after=86400,
        source_service_sha256=sha(sources['client/service.py']),
        adapted_service_sha256=sha(files['app/service.py']),
        bridge_removes_trial_limit=True, awake_lease_freshness_ms=2500,
        settings_entry_name_icon_source_preserved=True, public_distribution=False))
    for name, content in files.items():
        if name.endswith('.py'):
            ast.parse(content.decode('utf-8-sig'), feature_version=(3, 5))
        if pathlib.PurePosixPath(name).suffix.lower() in ('.ttf', '.otf', '.ttc', '.woff', '.woff2'):
            raise ValueError('Bundled fonts are forbidden')
    manifest = {name: dict(sha256=sha(content), bytes=len(content)) for name, content in sorted(files.items())}
    result = dict(release_id=release_id, session=release_id, remote=state_remote,
                  release_remote=release_remote, app_remote=app_remote, media_remote=media_remote,
                  source_identity_sha256=identity, original_sha256=PIN,
                  patched_sha256=sha(candidate), candidate_sha256=sha(candidate),
                  manifest_sha256=sha(canonical(manifest)), device_tested=False,
                  permanent_install_executed=False, public_distribution=False,
                  status='HOST_BUILT_DEVICE_PENDING', **evidence)
    output.mkdir(parents=True, exist_ok=False)
    for name, content in files.items():
        target = output/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    (output/'manifest.json').write_bytes(canonical(manifest))
    (output/'SOURCE.sha256').write_text(''.join(info['sha256']+' '+str(info['bytes'])+' '+name+'\n'
                                             for name, info in manifest.items()), encoding='ascii')
    (output/'build-result.json').write_bytes(canonical(result))
    for name, info in manifest.items():
        content = read_file(output/name)
        if len(content) != info['bytes'] or sha(content) != info['sha256']:
            raise ValueError('Payload readback failed: '+name)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-dir', type=pathlib.Path, required=True)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    args = parser.parse_args()
    output = build(args.native_dir, args.output)
    print(json.dumps(json.loads((output/'build-result.json').read_bytes()), indent=2))
    print('PAYLOAD='+str(output))


if __name__ == '__main__':
    main()
