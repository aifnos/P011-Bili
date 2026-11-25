"""Read currently scanned-out DRM framebuffer through a private read-only FD.

Never acquires DRM master, changes a mode, or writes any display buffer.
The returned GEM reference belongs only to this FD and is released on close.
"""
import base64
import datetime
import hashlib
import json
import zlib
from PIL import Image
from awake_trial import Adb, ROOT, result_from

PROBE=r'''
import os,ctypes as c,base64,zlib
class Resources(c.Structure):
 _fields_=[('nfb',c.c_int),('fbs',c.POINTER(c.c_uint32)),('ncrtc',c.c_int),('crtcs',c.POINTER(c.c_uint32)),('nconnector',c.c_int),('connectors',c.POINTER(c.c_uint32)),('nencoder',c.c_int),('encoders',c.POINTER(c.c_uint32)),('minw',c.c_uint32),('maxw',c.c_uint32),('minh',c.c_uint32),('maxh',c.c_uint32)]
class Crtc(c.Structure):
 _fields_=[('id',c.c_uint32),('fb',c.c_uint32),('x',c.c_uint32),('y',c.c_uint32),('w',c.c_uint32),('h',c.c_uint32),('valid',c.c_int),('mode',c.c_ubyte*68),('gamma',c.c_int)]
class FB(c.Structure):
 _fields_=[(n,c.c_uint32) for n in ('id','w','h','pitch','bpp','depth','handle')]
class Map(c.Structure):
 _fields_=[('handle',c.c_uint32),('pad',c.c_uint32),('offset',c.c_uint64)]
drm=c.CDLL('libdrm.so.2',use_errno=True);libc=c.CDLL(None,use_errno=True)
drm.drmModeGetResources.restype=c.POINTER(Resources);drm.drmModeGetResources.argtypes=[c.c_int]
drm.drmModeGetCrtc.restype=c.POINTER(Crtc);drm.drmModeGetCrtc.argtypes=[c.c_int,c.c_uint32]
drm.drmModeGetFB.restype=c.POINTER(FB);drm.drmModeGetFB.argtypes=[c.c_int,c.c_uint32]
libc.mmap.restype=c.c_void_p;libc.mmap.argtypes=[c.c_void_p,c.c_size_t,c.c_int,c.c_int,c.c_int,c.c_long]
libc.munmap.argtypes=[c.c_void_p,c.c_size_t]
fd=os.open('/dev/dri/card0',os.O_RDONLY|os.O_CLOEXEC);rows=[]
try:
 res=drm.drmModeGetResources(fd)
 if not res:raise OSError(c.get_errno(),'GETRESOURCES')
 if not 0<=res.contents.ncrtc<=4:raise ValueError('CRTC bound')
 for i in range(res.contents.ncrtc):
  ptr=drm.drmModeGetCrtc(fd,res.contents.crtcs[i])
  if not ptr:continue
  cr=ptr.contents;row=dict(crtc=cr.id,fb=cr.fb,x=cr.x,y=cr.y,width=cr.w,height=cr.h,mode_valid=cr.valid)
  if cr.fb and cr.valid:
   fb=drm.drmModeGetFB(fd,cr.fb)
   if not fb:row['getfb_errno']=c.get_errno()
   else:
    info=fb.contents;size=info.pitch*info.h
    row.update(fb_width=info.w,fb_height=info.h,pitch=info.pitch,bpp=info.bpp,depth=info.depth)
    if info.handle and info.bpp==32 and 0<info.w<=2048 and 0<info.h<=2048 and info.w*4<=info.pitch<=16384 and 0<size<=16*1024*1024:
     request=Map(info.handle,0,0)
     if libc.ioctl(fd,0xc01064b3,c.byref(request))!=0:row['map_errno']=c.get_errno()
     else:
      address=libc.mmap(None,size,1,1,fd,request.offset)
      if address is None or address==c.c_void_p(-1).value:row['mmap_errno']=c.get_errno()
      else:
       try:raw=c.string_at(address,size)
       finally:libc.munmap(address,size)
       row['pixels_zlib_b64']=base64.b64encode(zlib.compress(raw,6)).decode('ascii')
    drm.drmModeFreeFB(fb)
  rows.append(row);drm.drmModeFreeCrtc(ptr)
 drm.drmModeFreeResources(res)
finally:os.close(fd)
print('RESULT='+repr({'read_only':True,'rows':rows}))
'''

def main():
    out=ROOT/'logs'/('BiliP011-DRMCapture-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir();print('LOG_DIR='+str(out),flush=True)
    result=result_from(Adb(out).python('readonly-drm-scanout',PROBE,timeout=15))
    for row in result['rows']:
        packed=row.pop('pixels_zlib_b64',None)
        if packed:
            raw=zlib.decompress(base64.b64decode(packed));name='crtc-'+str(row['crtc'])
            (out/(name+'-pixels.raw')).write_bytes(raw)
            image=Image.frombytes('RGB',(row['fb_width'],row['fb_height']),raw,'raw','BGRX',row['pitch'],1)
            image.save(out/(name+'-scanout.png'))
            row.update(raw_sha256=hashlib.sha256(raw).hexdigest(),extrema=image.getextrema(),
                       color_interpretation='BGRX for legacy 32bpp framebuffer; no pixel edits')
    result['private']=True
    (out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
