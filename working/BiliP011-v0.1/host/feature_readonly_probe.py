"""Read-only capability/API shape checks, excluding URLs, accounts and titles."""
import datetime,json,urllib.parse
from official_contract_probe import fetch
from awake_trial import Adb,ROOT,result_from

def main():
    out=ROOT/'logs'/('BiliP011-FeatureReadOnly-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
    print('LOG_DIR='+str(out),flush=True)
    probe="""import os
result={}
for base in ('/usr/lib','/usr/lib/qt5/qml','/usr/bin'):
 try:result[base]=[n for n in os.listdir(base) if any(s in n.lower() for s in ('webengine','webkit','browser','gst-inspect'))]
 except OSError:result[base]=[]
print('RESULT='+repr(result))
"""
    result={'device':result_from(Adb(out).python('web-capabilities',probe))}
    paths=['https://api.live.bilibili.com/xlive/web-interface/v1/index/getList?platform=web']
    try:
        d=json.loads(fetch(paths[0]));result['live_catalog']={'code':d.get('code'),'keys':list(d.get('data',{}))}
        rooms=[]
        def walk(v):
            if isinstance(v,dict):
                if v.get('roomid') or v.get('room_id'):rooms.append(str(v.get('roomid') or v.get('room_id')))
                for item in v.values():walk(item)
            elif isinstance(v,list):
                for item in v:walk(item)
        walk(d.get('data',{}));result['live_catalog']['room_count']=len(set(rooms))
        if rooms:
            room=rooms[0]
            for name,path in [('info','/room/v1/Room/get_info?room_id='+room),('stream','/xlive/web-room/v2/index/getRoomPlayInfo?'+urllib.parse.urlencode(dict(room_id=room,protocol='0,1',format='0,1,2',codec='0',qn=150,platform='web',ptype=8)))]:
                raw=json.loads(fetch('https://api.live.bilibili.com'+path));item=raw.get('data',{}) or {};result['live_'+name]={'code':raw.get('code'),'keys':list(item)}
                if name=='stream':
                    info=item.get('playurl_info',{}).get('playurl',{});result['live_stream']['qualities']=info.get('g_qn_desc',[])
                    result['live_stream']['formats']=[{'protocol':s.get('protocol_name'),'format':f.get('format_name'),'codec':c.get('codec_name'),'qn':c.get('current_qn'),'url_hosts':[urllib.parse.urlsplit(u.get('host','')).hostname for u in c.get('url_info',[])]} for s in info.get('stream',[]) for f in s.get('format',[]) for c in f.get('codec',[])]
        result['no_account_writes']=True
    except Exception as exc:result['error']=type(exc).__name__
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
