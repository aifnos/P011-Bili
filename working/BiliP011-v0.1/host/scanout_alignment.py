"""Read-only DRM placement evidence. App-buffer metadata is not screen proof.

Only used in explicitly muted automated trials on public pages. The untouched
480x800 image is retained; coordinate interpretation happens in the analyzer,
not by rotating/cropping the evidence image.
"""
import base64
import hashlib
import json
import zlib
from PIL import Image
from capture_drm_scanout import PROBE as DRM_PROBE
from awake_trial import result_from


def analyze(image):
    if image.size != (480, 800):
        return {'passed': False, 'error': 'unexpected-scanout-size', 'size': list(image.size)}
    rgb = image.convert('RGB')
    # Output transform: logical (x,y) = (799 - raw_y, raw_x).
    # A correctly centered 800x268 window occupies raw columns [106,374).
    counts = [sum(max(rgb.getpixel((y, 799-x))) > 8 for x in range(800)) for y in range(480)]
    occupied = [y for y, n in enumerate(counts) if n > 8]
    first, last = (occupied[0], occupied[-1]) if occupied else (-1, -1)
    outside = sum(counts[:106]) + sum(counts[374:])
    # Fullscreen background must hide the factory/Qt page, including corners.
    passed = first == 106 and last == 373 and outside == 0 and min(counts[106:374]) >= 80
    return {'passed': passed, 'observed_y': first, 'observed_bottom_exclusive': last+1,
            'expected_y': 106, 'expected_height': 268, 'nonblack_outside': outside,
            'minimum_content_row_pixels': min(counts[106:374]),
            'raw_size': [480, 800], 'image_transformed': False,
            'method': 'current-drm-crtc-readonly', 'physical_touch_tested': False}


def capture(adb, out, name, context):
    result = result_from(adb.python('scanout-'+name, DRM_PROBE, timeout=15))
    rows = [row for row in result['rows'] if row.get('pixels_zlib_b64')]
    if len(rows) != 1:
        raise ValueError('Expected exactly one readable current CRTC')
    row = rows[0]
    if (row['fb_width'], row['fb_height'], row['bpp'], row['pitch']) != (480, 800, 32, 1920):
        raise ValueError('Unexpected scanout buffer geometry')
    raw = zlib.decompress(base64.b64decode(row.pop('pixels_zlib_b64')))
    if len(raw) != 480*800*4:
        raise ValueError('Unexpected scanout byte count')
    picture = Image.frombytes('RGB', (480, 800), raw, 'raw', 'BGRX', row['pitch'], 1)
    folder = out/'scanout'; folder.mkdir(exist_ok=True)
    image_path = folder/(name+'.png')
    if image_path.exists(): raise ValueError('Existing screen evidence')
    picture.save(image_path)
    report = dict(analyze(picture), context=context, framebuffer=row,
                  pixel_sha256=hashlib.sha256(raw).hexdigest(),
                  png_sha256=hashlib.sha256(image_path.read_bytes()).hexdigest())
    (folder/(name+'.json')).write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


# Read only numeric state before/after each capture, not account/API output.
STATE = r'''
import os,sys
sys.path.insert(0,ROOT+'/stdlib-json35.zip');sys.path.insert(0,ROOT)
import json,awake_trial as trial,config
trial.verify()
result={'player_running':False,'player_pid':0}
for row in trial.procs():
 if row['exe']==config.MEDIA+'/bin/bili-player' and trial.alive(row):
  try:
   if trial.environment(row).get('P011_CLIENT_ROOT')==ROOT:
    result['player_running']=True;result['player_pid']=row['pid']
  except (FileNotFoundError,ProcessLookupError):pass
for name in ('player-state.json','window-placement.json'):
 p=ROOT+'/'+name
 if os.path.isfile(p) and not os.path.islink(p) and os.path.getsize(p)<32768:
  with open(p) as f:obj=json.load(f)
  result[name]={k:v for k,v in obj.items() if isinstance(v,(bool,int,float))}
  if name=='player-state.json':result['player_mtime']=os.stat(p).st_mtime
print('RESULT='+repr(result))
'''


class Observer:
    def __init__(self, adb, meta, out):
        if not meta.get('ui_automation') or meta.get('player_protocol') != 2:
            raise ValueError('Screen checks require an explicit muted automated session')
        self.adb, self.meta, self.out = adb, meta, out
        self.pose=meta.get('window_pose')
        if self.pose is not None and (self.pose not in ('landscape','portrait') or meta.get('benchmark_quality')!=32 or meta.get('benchmark_bvid')!='BV1Da411Y7U4'):
            raise ValueError('Unknown single-pose diagnostic')
        self.samples, self.keys = [], set()
        self.first_mtime={}

    def poll(self):
        # A fixed-pose session never changes orientation after its one setup
        # action. Avoid repeated identity hashing once its stable output was
        # captured; it would only perturb the independent pause sampler.
        if self.pose and any(s['state_stable'] and s['passed'] for s in self.samples):return
        state = result_from(self.adb.python('scanout-state', 'ROOT='+repr(self.meta['remote'])+'\n'+STATE))
        p, placement = state.get('player-state.json', {}), state.get('window-placement.json', {})
        if not state.get('player_running') or not p.get('loaded') or not p.get('active') or not p.get('muted') or p.get('switch_pending'):
            return
        if self.pose and bool(p.get('portrait'))!=(self.pose=='portrait'):return
        pid=state['player_pid'];mtime=state.get('player_mtime',0)
        if pid not in self.first_mtime:
            self.first_mtime[pid]=mtime;return
        if mtime<=self.first_mtime[pid]:return
        if not placement.get('configure_confirmed'):
            raise ValueError('Fullscreen configure has not been confirmed')
        key = (p.get('generation', 0), bool(p.get('portrait')), p.get('menu', 0))
        if key[2] not in (0,1,8):return
        if key in self.keys or len(self.samples) >= 12: return
        context = dict(generation=key[0], portrait=key[1], menu=key[2],
                       hardware=p.get('hardware_backend'), muted=True, player_pid=pid)
        sample = capture(self.adb, self.out, '%02d'%len(self.samples), context)
        after_state = result_from(self.adb.python('scanout-after', 'ROOT='+repr(self.meta['remote'])+'\n'+STATE))
        after = after_state.get('player-state.json', {})
        sample['state_before']={k:p.get(k) for k in ('generation','portrait','menu','active','loaded','paused','switch_pending')}
        sample['state_after']={k:after.get(k) for k in ('generation','portrait','menu','active','loaded','paused','switch_pending')}
        sample['state_stable'] = all(p.get(k) == after.get(k) for k in ('generation','portrait','menu')) and bool(after.get('active')) and after_state.get('player_running',False) and after_state.get('player_pid')==pid
        (self.out/'scanout'/('%02d.json'%len(self.samples))).write_text(json.dumps(sample,indent=2),encoding='utf-8')
        self.samples.append(sample)
        if sample['state_stable']:
            self.keys.add(key)
            if not sample['passed']: raise ValueError('Actual screen placement failed')

    def result(self):
        stable = [s for s in self.samples if s['state_stable']]
        orientations = {s['context']['portrait'] for s in stable}
        generations = {s['context']['generation'] for s in stable}
        coverage=orientations=={self.pose=='portrait'} and len(generations)==1 if self.pose else orientations=={False,True} and len(generations)>=2
        return {'passed': bool(stable) and all(s['passed'] for s in stable) and coverage,
                'samples': self.samples, 'stable_count': len(stable),
                'orientations_covered': len(orientations), 'generations_covered': len(generations),
                'profile': self.pose or 'full-regression',
                'required': ('one fixed-source '+self.pose+' session; pair with separate opposite-pose session' if self.pose else 'landscape, portrait, two player generations; all stable screen samples aligned'),
                'physical_touch_tested': False}
