"""Read-only, numeric DMA/ION topology probe; never mounts debugfs or allocates GPU memory."""
import datetime
import json

from probe_device import ROOT, NATIVE, Adb, result_from, archive


PAYLOAD = r'''
import glob,gzip,os,re,struct
r={'device_writes':False,'graphics_allocations':False}
def data(path,limit=65536):
 with open(path,'rb') as f:return f.read(limit)
def cells(value):
 if len(value)%4:return []
 return list(struct.unpack('>'+str(len(value)//4)+'I',value))
def number(value):
 n=0
 for v in value:n=(n<<32)|v
 return n
r['kernel_config']={}
try:
 with gzip.open('/proc/config.gz','rb') as f:config=f.read(524288).decode('ascii','replace')
 prefixes=('CONFIG_CMA','CONFIG_DMA_CMA','CONFIG_DMA_DECLARE_COHERENT','CONFIG_ION','CONFIG_SPRD_ION','CONFIG_ARM_LPAE','CONFIG_HIGHMEM','CONFIG_COMPACTION','CONFIG_MIGRATION','CONFIG_FORCE_MAX_ZONEORDER','CONFIG_DRM_SPRD','CONFIG_ZONE_DMA','CONFIG_DEBUG_FS','CONFIG_KALLSYMS')
 for line in config.splitlines():
  clean=line[2:] if line.startswith('# ') else line
  if any(clean.startswith(k+'=') or clean.startswith(k+'_') or clean==k+' is not set' for k in prefixes):
   if '=' in clean:k,v=clean.split('=',1)
   else:k,v=clean.split(' ',1)[0],'n'
   r['kernel_config'][k]=v
except OSError:r['kernel_config_available']=False
dt='/sys/firmware/devicetree/base'
r['reserved_regions']=[]
parent=dt+'/reserved-memory'
if os.path.isdir(parent):
 ac=number(cells(data(parent+'/#address-cells',8))) if os.path.isfile(parent+'/#address-cells') else 1
 sc=number(cells(data(parent+'/#size-cells',8))) if os.path.isfile(parent+'/#size-cells') else 1
 for path in sorted(glob.glob(parent+'/*')):
  if not os.path.isdir(path):continue
  item={'name':os.path.basename(path).split('@')[0]}
  for key in ('compatible','status'):
   if os.path.isfile(path+'/'+key):item[key]=data(path+'/'+key,512).decode('ascii','replace').strip('\0').replace('\0',',')
  if os.path.isfile(path+'/reg'):
   values=cells(data(path+'/reg',256));stride=ac+sc
   if 0<stride<=8:item['sizes_bytes']=[number(values[i+ac:i+stride]) for i in range(0,len(values),stride) if len(values[i:i+stride])==stride]
  item['no_map']=os.path.isfile(path+'/no-map');item['reusable']=os.path.isfile(path+'/reusable')
  r['reserved_regions'].append(item)
r['ion_nodes']=[]
for path,dirs,files in os.walk(dt):
 if 'ion' not in os.path.basename(path).lower():continue
 item={'name':os.path.basename(path).split('@')[0],'children':[]}
 for child in [path]+[os.path.join(path,d) for d in dirs]:
  row={'name':os.path.basename(child).split('@')[0]}
  for key in ('compatible','status','heap-name','label'):
   if os.path.isfile(child+'/'+key):row[key]=data(child+'/'+key,256).decode('ascii','replace').strip('\0').replace('\0',',')
  for key in ('reg','type','heap-id','heap-type','memory-region','sprd,ion-heap-id','sprd,ion-heap-type'):
   if os.path.isfile(child+'/'+key):row[key]=cells(data(child+'/'+key,64))
  row['property_names']=sorted(n for n in os.listdir(child) if os.path.isfile(child+'/'+n))
  item['children'].append(row)
 r['ion_nodes'].append(item)
r['debugfs_mounts']=[]
for line in data('/proc/mounts').decode('ascii','replace').splitlines():
 fields=line.split()
 if len(fields)>2 and fields[2]=='debugfs':r['debugfs_mounts'].append(fields[1])
r['debug_directory_names']={}
for path in ('/sys/kernel/debug','/sys/kernel/ion','/sys/class/misc/ion','/sys/class/drm'):
 try:r['debug_directory_names'][path]=sorted(os.listdir(path))[:128]
 except OSError:r['debug_directory_names'][path]=None
r['graphics_processes']=[]
for path in glob.glob('/proc/[0-9]*'):
 try:
  comm=data(path+'/comm',64).decode('ascii','replace').strip()
  if comm not in ('Z03','weston','bili-player','bili-hw'):continue
  fd_counts={};dma_entries=0
  for fd in glob.glob(path+'/fd/*'):
   try:target=os.readlink(fd)
   except OSError:continue
   key=next((n for n in ('/dev/dri/','/dev/mali','/dev/ion','dmabuf') if n in target),None)
   if key:fd_counts[key]=fd_counts.get(key,0)+1
  for fi in glob.glob(path+'/fdinfo/*'):
   try:body=data(fi,4096).decode('ascii','replace')
   except OSError:continue
   if 'exp_name:' in body:dma_entries+=1
  r['graphics_processes'].append({'pid':int(os.path.basename(path)),'name':comm,'graphics_fd_counts':fd_counts,'dmabuf_fdinfo_count':dma_entries})
 except OSError:pass
r['symbol_presence']={k:None for k in ('sprd_gem_cma_dumb_create','ion_new_alloc','dma_alloc_from_contiguous','ion_system_heap_allocate','ion_carveout_heap_allocate')}
try:
 with open('/proc/kallsyms') as f:
  r['symbol_presence']={k:False for k in r['symbol_presence']}
  for line in f:
   values=line.split()
   if len(values)>2 and values[2] in r['symbol_presence']:r['symbol_presence'][values[2]]=True
except OSError:pass
r['ion_heap_query']={'allocation_requests':0}
try:
 import ctypes
 libc=ctypes.CDLL('libc.so.6',use_errno=True)
 libc.ioctl.restype=ctypes.c_int
 def heap_query(fd,q):
  buf=ctypes.create_string_buffer(bytes(q),len(q))
  rc=libc.ioctl(ctypes.c_int(fd),ctypes.c_ulong(0xc0184908),ctypes.byref(buf))
  if rc<0:raise OSError(ctypes.get_errno(),'ION_HEAP_QUERY')
  return buf.raw
 class Heap(ctypes.Structure):
  _fields_=[('name',ctypes.c_char*32),('type',ctypes.c_uint32),('heap_id',ctypes.c_uint32),('r0',ctypes.c_uint32),('r1',ctypes.c_uint32),('r2',ctypes.c_uint32)]
 assert ctypes.sizeof(Heap)==52 and struct.calcsize('<IIQII')==24
 fd=os.open('/dev/ion',os.O_RDONLY|os.O_CLOEXEC)
 try:
  q=bytearray(struct.pack('<IIQII',0,0,0,0,0))
  q=heap_query(fd,q)
  count=struct.unpack('<IIQII',q)[0]
  assert 0<=count<=32
  r['ion_heap_query']['reported_count']=count
  if count:
   heaps=(Heap*count)();q=bytearray(struct.pack('<IIQII',count,0,ctypes.addressof(heaps),0,0))
   q=heap_query(fd,q)
   returned=struct.unpack('<IIQII',q)[0];assert returned<=count
   r['ion_heap_query']['heaps']=[{'name':heaps[i].name.decode('ascii','replace'),'type':heaps[i].type,'heap_id':heaps[i].heap_id} for i in range(returned)]
 finally:os.close(fd)
except OSError as e:r['ion_heap_query']['errno']=e.errno
except ImportError:r['ion_heap_query']['unsupported_python_modules']=True
r['boot_identity']={'checked':False}
try:
 import hashlib,stat
 dev='/dev/mmcblk0p27'
 assert 'PARTNAME=boot' in data('/sys/class/block/mmcblk0p27/uevent',4096).decode('ascii').splitlines()
 length=int(data('/sys/class/block/mmcblk0p27/size',64))*512
 assert length==36700160 and stat.S_ISBLK(os.stat(dev).st_mode)
 h=hashlib.sha256();read_bytes=0
 with open(dev,'rb') as f:
  while read_bytes<length:
   block=f.read(min(1048576,length-read_bytes));assert block
   h.update(block);read_bytes+=len(block)
 r['boot_identity']={'checked':True,'bytes':read_bytes,'sha256':h.hexdigest(),'matches_backup':h.hexdigest()=='b62e65297faa7e45b1188175310793450fbee93a46e04f100eaf4d57537ab903'}
except OSError as e:r['boot_identity']['errno']=e.errno
print('RESULT='+repr(r))
'''


def main():
    out = ROOT / 'logs' / ('BiliP011-GraphicsHeaps-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir()
    adb = Adb(out)
    safety = (NATIVE / 'runtime/native_safety.py').read_text(encoding='utf-8')
    gate = safety + '\ns=stock_snapshot();require_stock(s);print("RESULT="+repr(s))'
    before = result_from(adb.python('before', gate))
    report = {}
    try:
        report = result_from(adb.python('heap-topology', PAYLOAD))
    finally:
        after = result_from(adb.python('after', gate))
        report['stock_unchanged'] = before == after
        (out / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))
        print('LOG_DIR=' + str(out))
        archive(out)
    if not report['stock_unchanged']:
        raise RuntimeError('Stock identity changed during read-only probe')


if __name__ == '__main__':
    main()
