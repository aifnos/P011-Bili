"""Offline read-only extraction of exact v2.4.0 navigation resources."""
import hashlib,json,struct,zlib
from build_awake_trial import ORIGINAL,PIN,BASE
data=ORIGINAL.read_bytes();assert hashlib.sha256(data).hexdigest()==PIN
tree,names,body_at=0x1a3acc,0x1a5efc,0x1a9f54
out=BASE/'out'/('v240-layout-'+PIN[:16]);out.mkdir(exist_ok=True)
records={}
def walk(index,parent):
 at=tree+index*22;no,flags=struct.unpack_from('>IH',data,at)
 pos=names+no;length=struct.unpack_from('>H',data,pos)[0]
 name=data[pos+6:pos+6+length*2].decode('utf-16-be');path=parent+'/'+name if index else ''
 if flags&2:
  count,first=struct.unpack_from('>II',data,at+6)
  for i in range(first,first+count):walk(i,path)
 else:
  offset=body_at+struct.unpack_from('>I',data,at+10)[0];size=struct.unpack_from('>I',data,offset)[0];body=data[offset+4:offset+4+size]
  if flags&1:body=zlib.decompress(body[4:])
  if path in ('/main.qml','/NaviPanel.qml') or path.endswith('/Style.qml') or path.endswith('/ZybKeyBoard.qml'):
   target=out/path[1:];target.parent.mkdir(parents=True,exist_ok=True)
   if target.exists():assert target.read_bytes()==body
   else:target.write_bytes(body)
   records[path]={'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()}
walk(0,'')
print(json.dumps({'output':str(out),'resources':records},indent=2))
