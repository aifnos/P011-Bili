"""Read fb0 pixels without input or display changes. Capture is private by default."""
import base64
import datetime
import hashlib
import json
import zlib
from PIL import Image
from awake_trial import Adb, ROOT, result_from

PROBE=r'''
import os,struct,base64,zlib
answer={'read_only':True}
fd=os.open('/dev/fb0',os.O_RDONLY)
try:
 try:
  import ctypes
  libc=ctypes.CDLL(None,use_errno=True);v=ctypes.create_string_buffer(160)
  if libc.ioctl(fd,0x4600,v)!=0:raise OSError(ctypes.get_errno(),'FBIOGET_VSCREENINFO')
  fields=struct.unpack('<40I',v.raw)
  width,height,xvirtual,yvirtual,xoffset,yoffset,bpp=fields[:7]
  channels={'red':list(fields[8:11]),'green':list(fields[11:14]),'blue':list(fields[14:17]),'alpha':list(fields[17:20])}
  answer['format_source']='FBIOGET_VSCREENINFO read-only ioctl'
 except ImportError:
  with open('/sys/class/graphics/fb0/virtual_size') as f:width,height=map(int,f.read().strip().split(','))
  with open('/sys/class/graphics/fb0/bits_per_pixel') as f:bpp=int(f.read().strip())
  with open('/sys/class/graphics/fb0/pan') as f:xoffset,yoffset=map(int,f.read().strip().split(','))
  channels={'red':[16,8,0],'green':[8,8,0],'blue':[0,8,0],'alpha':[24,8,0]}
  answer['format_source']='provisional BGRX from sysfs geometry; colors not verified'
 with open('/sys/class/graphics/fb0/stride') as f:stride=int(f.read().strip())
 if bpp!=32 or not (0<width<=2048 and 0<height<=2048) or not (width*4<=stride<=8192) or xoffset or stride*(yoffset+height)>8*1024*1024:raise ValueError('Unsupported framebuffer geometry')
 os.lseek(fd,yoffset*stride,os.SEEK_SET);data=b'';size=stride*height
 while len(data)<size:
  chunk=os.read(fd,min(65536,size-len(data)))
  if not chunk:break
  data+=chunk
 answer.update(width=width,height=height,stride=stride,bpp=bpp,xoffset=xoffset,yoffset=yoffset,
   channels=channels,
   bytes=len(data),pixels_zlib_b64=base64.b64encode(zlib.compress(data,6)).decode('ascii'))
finally:os.close(fd)
print('RESULT='+repr(answer))
'''

def main():
    out=ROOT/'logs'/('BiliP011-FramebufferCapture-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir();print('LOG_DIR='+str(out),flush=True)
    value=result_from(Adb(out).python('readonly-framebuffer',PROBE,timeout=12))
    raw=zlib.decompress(base64.b64decode(value.pop('pixels_zlib_b64')))
    if len(raw)!=value['stride']*value['height']:raise ValueError('Incomplete framebuffer read')
    (out/'fb0-pixels.raw').write_bytes(raw)
    shifts={k:v[0] for k,v in value['channels'].items()}
    if any(value['channels'][c][1:]!=[8,0] for c in ('red','green','blue')):raise ValueError('Unsupported pixel format')
    order={0:'X',8:'X',16:'X',24:'X'}
    for field,letter in (('red','R'),('green','G'),('blue','B')):order[shifts[field]]=letter
    mode=''.join(order[k] for k in (0,8,16,24))
    image=Image.frombytes('RGB',(value['width'],value['height']),raw,'raw',mode,value['stride'],1)
    image.save(out/'framebuffer-native.png')
    value.update(raw_sha256=hashlib.sha256(raw).hexdigest(),extrema=image.getextrema(),
                 capture='fb0 read, not yet proven to be active compositor scanout',private=True)
    (out/'result.json').write_text(json.dumps(value,indent=2),encoding='utf-8')
    print(json.dumps(value,indent=2))

if __name__=='__main__':main()
