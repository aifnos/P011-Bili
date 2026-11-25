"""Read-only numeric graphics allocation evidence, no raw kernel archive."""
import datetime,json
from probe_device import ROOT,NATIVE,Adb,result_from,archive

out=ROOT/'logs'/('BiliP011-GraphicsBudget-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
adb=Adb(out);safety=(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8');gate=safety+'\ns=stock_snapshot();require_stock(s);print("RESULT="+repr(s))'
before=result_from(adb.python('before',gate))
report=result_from(adb.python('numeric-graphics',r'''
import os,subprocess,glob,re
mem={}
for line in open('/proc/meminfo'):
 key,value=line.split(':',1)
 if key in ('CmaTotal','CmaFree','MemAvailable','MemFree','Cached','Buffers','Slab','SReclaimable','Shmem','Unevictable'):mem[key]=int(value.split()[0])
r={'memory_kb':mem,'ion':{}}
r['buddy_orders']=[]
try:
 for line in open('/proc/buddyinfo'):
  fields=line.split()
  if len(fields)>5 and fields[3] in ('DMA','DMA32','Normal','HighMem','Movable'):
   r['buddy_orders'].append({'zone':fields[3],'free_blocks_by_order':[int(n) for n in fields[4:]]})
except (OSError,ValueError):pass
for name in ('total_heaps_kb','total_pools_kb'):
 try:r['ion'][name]=int(open('/sys/kernel/ion/'+name).read())
 except (OSError,ValueError):pass
r['debug_files']=glob.glob('/sys/kernel/debug/ion/*')+glob.glob('/sys/kernel/debug/dma_buf/*')
p=subprocess.Popen(['dmesg'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL);body=p.communicate(timeout=4)[0].decode('ascii','replace')
keys=('ion_new_alloc','dumb buffer fail','alloc failed','allocation failure')
r['kernel_match_counts']={key:body.count(key) for key in keys}
r['recent_failure_numbers']=[]
for line in body.splitlines():
 if any(key in line for key in keys):r['recent_failure_numbers'].append(re.findall(r'[0-9]+(?:\.[0-9]+)?',line)[:12])
r['recent_failure_numbers']=r['recent_failure_numbers'][-8:]
r['failure_templates']=[]
for line in body.splitlines():
 if 'ion_new_alloc' in line or 'dumb buffer fail' in line:
  template=re.sub(r'0x[0-9a-fA-F]+|\b[0-9a-fA-F]{8,16}\b|[0-9]+(?:\.[0-9]+)?','<n>',line)
  if template not in r['failure_templates']:r['failure_templates'].append(template[:256])
print('RESULT='+repr(r))
'''))
after=result_from(adb.python('after',gate));report.update(stock_unchanged=before==after,device_writes=False)
(out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2));print('LOG_DIR='+str(out));archive(out)
