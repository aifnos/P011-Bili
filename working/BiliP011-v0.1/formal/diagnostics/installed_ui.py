"""Scoped native Linux input and read-only DRM capture for the installed page."""
import argparse
import base64
import datetime
import importlib.util
import json
from pathlib import Path
import sys
import zlib

FORMAL=Path(__file__).resolve().parents[1]
PKG=FORMAL/'out/P011-Bili-ADB-v8-reinstall-cache-20261014'
spec=importlib.util.spec_from_file_location('installed_reader',PKG/'install_formal.py')
R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)
sys.path.insert(0,str(FORMAL.parent/'host'))

COMMON=r'''
import os,stat,struct,ctypes as c,hashlib,time
assert os.getuid()==0
assert hashlib.sha256(open('/usr/bin/Z03','rb').read()).hexdigest()=='3526b379c4083092c9c282d4d749d2e5c72d89e56730bf08c975e3222ed42896'
assert open('/sys/class/input/event2/device/name').read().strip()=='cst1xx'
assert stat.S_ISCHR(os.stat('/dev/input/event2').st_mode)
'''

INFO=COMMON+r'''
libc=c.CDLL(None,use_errno=True);fd=os.open('/dev/input/event2',os.O_RDONLY|os.O_NONBLOCK)
rows={}
try:
 for code in (0,1,0x2f,0x35,0x36,0x39):
  data=c.create_string_buffer(24)
  rc=libc.ioctl(fd,0x80184540+code,data)
  rows[str(code)]=dict(supported=rc==0,values=list(struct.unpack('<6i',data.raw)) if rc==0 else [])
finally:os.close(fd)
print('RESULT='+repr(rows))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('info','capture','tap','swipe'))
    parser.add_argument('--transport',type=int,required=True)
    parser.add_argument('--points',type=int,nargs='+')
    args=parser.parse_args()
    stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    out=FORMAL/'evidence'/('installed-ui-'+args.action+'-'+stamp);out.mkdir()
    adb=R.Adb(out,args.transport)
    if args.action=='info':
        value=R.result(adb.python('input-capabilities',INFO))
    elif args.action=='capture':
        import capture_drm_scanout as C
        from PIL import Image
        value=R.result(adb.python('drm-scanout',COMMON+'\n'+C.PROBE,20))
        for row in value['rows']:
            packed=row.pop('pixels_zlib_b64',None)
            if packed:
                raw=zlib.decompress(base64.b64decode(packed))
                image=Image.frombytes('RGB',(row['fb_width'],row['fb_height']),raw,'raw','BGRX',row['pitch'],1)
                image.save(out/'scanout-native.png')
                # Display the captured pixels in the application's logical
                # orientation; this does not alter the device's rotation.
                logical=image.transpose(Image.Transpose.ROTATE_270)
                logical.save(out/'screen-landscape.png')
                # The scanout buffer is taller than the physical panel. The
                # owner's photo confirms only y=106..373 is visible on glass;
                # never diagnose off-panel buffer pixels as visible overlays.
                if logical.size==(800,480):
                    logical.crop((0,106,800,374)).save(out/'screen-visible.png')
                    row['physical_visible_crop']=[0,106,800,374]
                row['raw_sha256']=__import__('hashlib').sha256(raw).hexdigest()
    else:
        if not args.points or len(args.points)!=(2 if args.action=='tap' else 4):
            parser.error('Explicit observed input coordinates required')
        if any(not 0<=n<=4095 for n in args.points):raise ValueError('Input coordinate limit')
        code=COMMON+'\nPOINTS='+repr(args.points)+'\nACTION='+repr(args.action)+r'''
fd=os.open('/dev/input/event2',os.O_WRONLY|os.O_NONBLOCK)
def event(kind,code,value):os.write(fd,struct.pack('<llHHi',0,0,kind,code,value))
def position(x,y):
 event(3,0x35,x);event(3,0x36,y);event(0,0,0)
try:
 event(3,0x2f,0);event(3,0x39,123);event(1,0x14a,1)
 position(POINTS[0],POINTS[1])
 if ACTION=='swipe':
  for i in range(1,17):
   time.sleep(.018)
   position(round(POINTS[0]+(POINTS[2]-POINTS[0])*i/16),round(POINTS[1]+(POINTS[3]-POINTS[1])*i/16))
 else:time.sleep(.08)
 event(3,0x39,-1);event(1,0x14a,0);event(0,0,0)
finally:os.close(fd)
time.sleep(.4)
print('RESULT='+repr(dict(injected_native_input=True,action=ACTION,points=POINTS)))
'''
        value=R.result(adb.python('native-'+args.action,code))
    (out/'result.json').write_text(json.dumps(value,indent=2),encoding='utf8')
    print('EVIDENCE='+str(out))
    print(json.dumps(value,indent=2))


if __name__=='__main__':main()
