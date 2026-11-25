"""Whitelist-only client result ZIP. Original diagnostic logs stay local.

Factory stdout/stderr can contain factory account tokens / device identities,
even if Bili credentials never enter them. They and the copied factory binary
are deliberately excluded, rather than relying on imperfect text redaction.
"""
import hashlib,json,pathlib,re,zipfile

CAPTURES = ('01-recommendations','02-next-cards','03-video-details','04-offline-keyboard',
            '05-search-input','06-search-results','07-bangumi','08-input-error',
            '09-description','10-qualities','11-comments','12-comments-next','13-bangumi-details','14-comment-replies','15-bangumi-scrolled','16-input-component','17-api-high-qualities',
            'player-landscape','player-paused','player-quality','player-danmaku',
            'player-portrait','player-portrait-controls','player-next',
            'player-codecs','player-hevc','player-av1','player-types','player-types-later','player-dm-settings','player-story','player-story-next',
            'player-dm-layout','player-dm-half','player-aspect','player-fill','player-stats','player-story-drag','player-seek-preview',
            'toolbox-home','toolbox-files','toolbox-text','toolbox-image','toolbox-snake','toolbox-2048',
            'toolbox-bricks','toolbox-dashboard','toolbox-curves','toolbox-processes',
            'feature-live-list','feature-live-detail','player-comments','player-listen','player-live',
            'catalog-popular','catalog-weekly','catalog-timeline','player-subtitles','player-chapters','player-subtitle-settings','player-timed-preview')

def capture_rect(name,width,height,surface=None):
    if name not in CAPTURES or width!=800:raise ValueError('Unexpected raw capture geometry')
    strip=bool(name.startswith('player-') and surface and surface.get('content_only') is True)
    if strip:
        if height!=268 or (surface.get('buffer_width'),surface.get('buffer_height'),surface.get('panel_origin_y'),surface.get('configure_bound_ms'))!=(800,268,106,500):
            raise ValueError('Strip capture and runtime surface evidence differ')
        return [0,0,800,268]
    if height!=480:raise ValueError('Unexpected raw capture geometry')
    return [0,106,800,268]


def crop_captures(out):
    # Preserve exact device window captures. Only the derived view removes the
    # known factory's unused 106px margins; never rotate/repair the actual UI.
    from PyQt5.QtGui import QImage
    out=pathlib.Path(out);report=[]
    metadata=out/'device/surface-info.json'
    surface=json.loads(metadata.read_text(encoding='utf-8')) if metadata.is_file() and not metadata.is_symlink() else None
    for name in CAPTURES:
        path=out/'device/screenshots'/(name+'.png')
        if not path.is_file() or path.is_symlink():continue
        picture=QImage(str(path))
        rectangle=capture_rect(name,picture.width(),picture.height(),surface)
        dest=out/'ui-crops'/(name+'.png');dest.parent.mkdir(exist_ok=True)
        if dest.exists():raise ValueError('Existing derived capture')
        crop=picture.copy(*rectangle)
        if not crop.save(str(dest)):raise RuntimeError('Content crop failed')
        sample=crop.scaled(80,27)
        colors=set(sample.pixelColor(x,y).rgb() for y in range(sample.height()) for x in range(sample.width()))
        if len(colors)<16:raise RuntimeError('Blank or nearly uniform capture: '+name)
        report.append({'name':name,'raw_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                       'crop_sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'crop_rect':rectangle,
                       'raw_size':[picture.width(),picture.height()]})
    (out/'capture-index.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    player=[x['crop_sha256'] for x in report if x['name'].startswith('player-')]
    if len(player)>=7 and len(set(player))<6:raise RuntimeError('Player captures did not visibly change with controls/orientation')
    return report

def archive_client(out):
    out=pathlib.Path(out).resolve()
    allowed={
        'bundle.json','result.json','independent-stock.json','user-feedback.md',
        'device/events.jsonl','device/result.json','device/player-state.json',
        'device/player-result.json','device/player-primary-result.json','device/media-state.json','device/capture-state.json','device/render-info.json','device/screenshots/decoder-reference.png',
        'device/performance-result.json','device/playback-settings.json','device/hardware-error.json','device/hardware-lifecycle.json','device/hardware-graphics.json',
        'device/phase-result.json',
        'device/prefetch-result.json','device/gesture-result.json','device/story-loop-result.json',
        'device/dm-delay-probe.json','device/live-danmaku-result.json',
        'device/performance-qa.json','performance-samples.json',
        'device/drm-allocation.json','device/frame-pacing.json',
        'device/presentation-feedback.json',
        'device/presentation-startup.json',
        'device/surface-info.json',
        'device/window-placement.json',
        'device/display-prepare.json',
        'device/hardware-seek.json',
        'device/hardware-seek-reload.json',
        'device/play-diagnostic.json','device/player-startup.json',
        'device/ui-qa-result.json','capture-index.json','soak-samples.json',
    }
    # Fixed public UI captures only. Never glob arbitrary PNGs (QR/account).
    allowed.update('device/screenshots/'+name+'.png' for name in CAPTURES)
    allowed.update('ui-crops/'+name+'.png' for name in CAPTURES)
    # Only stable public automated-player captures with verified black outer
    # margins are shareable. Failed/transition scanouts remain private locally.
    report_path=out/'result.json'
    if report_path.is_file():
        alignment=json.loads(report_path.read_text(encoding='utf-8')).get('screen_alignment',{})
        for index,sample in enumerate(alignment.get('samples',[])[:12]):
            if sample.get('state_stable') is True and sample.get('passed') is True:
                allowed.update('scanout/%02d.%s'%(index,ext) for ext in ('png','json'))
    # UI emits only fixed names/counts. Extract those exact suffixes, never a
    # vendor line, arbitrary API message, title, URL or displayed account name.
    marker=re.compile(r'P011_(?:AWAKE (?:READY|RELEASE|ACQUIRE)|BILI (?:UI_READY|UI_DESTROYED|SCENE_ENTERED|PLAY_REQUEST|LOGIN_CONFIRMED|PAGE (?:catalog (?:recommend|search|following|bangumi)|detail|searchInput|openInput|account)|LIST (?:recommend|search|following|bangumi) [0-9]{1,3}))(?=\s*$)')
    events=[]
    for name in ('device/candidate.stdout.raw','device/candidate.stderr.raw'):
        path=out/name
        if not path.is_file():continue
        for line in path.read_text(encoding='utf-8',errors='replace').splitlines():
            line=re.sub(r'\x1b\[[0-9;]*m','',line)
            match=marker.search(line)
            if match:events.append(match.group())
    target=out.with_name(out.name+'-safe.zip')
    with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED) as z:
        for name in sorted(allowed):
            path=out/name
            if path.is_file() and not path.is_symlink():
                # Some reduced mpv builds cannot encode a decoder-reference
                # screenshot. Keep that raw diagnostic locally, not as a
                # broken image in the shareable visual-evidence archive.
                if name=='device/screenshots/decoder-reference.png':
                    with path.open('rb') as f:header=f.read(8)
                    if header!=b'\x89PNG\r\n\x1a\n':continue
                z.write(path,name)
        z.writestr('ui-events.safe.txt','\n'.join(events)+'\n')
        z.writestr('PRIVACY.txt','Bili cookies, QR content, API bodies, signed stream URLs, factory raw logs and factory binaries are excluded. Original raw diagnostics remain in the local logs directory; do not share those raw files. Account data is stored only in the pen private bili-account directory. This ZIP reports technical evidence, not physical acceptance.\n')
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        assert set(z.namelist()).issubset(allowed|{'ui-events.safe.txt','PRIVACY.txt'})
    print('SAFE_RESULT_ZIP='+str(target),flush=True)
    print('ZIP_SHA256='+hashlib.sha256(target.read_bytes()).hexdigest(),flush=True)
    return target

if __name__=='__main__':
    import sys
    archive_client(sys.argv[1])
