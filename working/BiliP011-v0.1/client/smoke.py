"""Anonymous target-native smoke; only summarized results cross ADB.

No window, audio, QR request, account file, vendor IPC or radio manipulation.
Uses the newly staged candidate's private helper and matching JSON package.
"""
import os
import sys
import time
import signal
import ctypes
import service
import config as C
from native_safety import require_stock, stock_snapshot


def main():
    signal.alarm(125)
    libc=ctypes.CDLL(None)
    class Limit(ctypes.Structure): _fields_=[('cur',ctypes.c_ulong),('max',ctypes.c_ulong)]
    libc.setrlimit(4,ctypes.byref(Limit(0,0)))
    before=stock_snapshot();require_stock(before)
    env=dict(os.environ,LD_LIBRARY_PATH=C.MEDIA+'/lib')
    for key in ('http_proxy','https_proxy','all_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','LD_PRELOAD'):env.pop(key,None)
    b=service.Backend(C.REMOTE,C.MEDIA+'/bin/bili-api','',C.REMOTE+'/no-anonymous-account',env,lifetime=115)
    result={'device_native':True,'account_used':False,'audio_played':False,'window_opened':False,'checks':{}}
    def execute(op,args):
        try:
            value=b.helper(op,args)
            return value, None
        except service.Failure as exc:return None,service.error_result(exc)
    try:
        pending={op:b.submit(op,args) for op,args in (
            ('recommend',{}),('search',{'query':'开源硬件'}),('bangumi',{}),('status',{}),
            ('following',{}),('detail',{'kind':'video','bvid':'BV1Da411Y7U4'}))}
        complete={};deadline=time.monotonic()+90
        while pending and time.monotonic()<deadline:
            for op,key in list(pending.items()):
                answer=b.result(key)
                if not answer.get('pending'):complete[op]=answer;del pending[op]
            time.sleep(.1)
        for op,answer in complete.items():
            entry={'ok':answer.get('ok') is True}
            if entry['ok']:
                d=answer['data']
                if 'items' in d:entry['items']=len(d['items']);entry['more']=d['more']
                if 'parts' in d:entry['parts']=len(d['parts'])
                if op=='status':entry['logged_in']=d['logged_in']
            else:entry.update(error=answer.get('error'),code=answer.get('code'))
            result['checks'][op]=entry
        result['unfinished']=list(pending)
        details=complete.get('detail',{})
        if details.get('ok') and details['data']['parts']:
            data,error=execute('play',details['data']['parts'][0])
            result['checks']['video_stream']={'ok':bool(data and data.get('video')),'separate_audio':bool(data and data.get('audio')),'played':False}
            if error:result['checks']['video_stream'].update(error)
        result['checks']['offline_pinyin']={'ok':any(x['text']=='电影' for x in b.lookup_pinyin('dianying')['candidates'])}
        rows=complete.get('recommend',{}).get('data',{}).get('items',[])
        if rows and rows[0].get('cover_key'):
            try:
                image=b.dispatch('thumbnail',{'key':rows[0]['cover_key']},0)
                result['checks']['thumbnail']={'ok':image['source'].startswith('data:image/'),'base64_chars':len(image['source'])}
            except service.Failure as exc:result['checks']['thumbnail']=service.error_result(exc)
    finally:
        b.close();after=stock_snapshot();require_stock(after)
        result['stock_hashes_unchanged']=before['hashes']==after['hashes']
        result['stock_processes_unchanged']=before['processes']==after['processes']
    # API code 0 alone is not a successful search acceptance.
    result['passed']=all(result['checks'].get(k,{}).get('ok') for k in ('recommend','search','bangumi','detail','status','video_stream','offline_pinyin','thumbnail')) and all(result['checks'].get(k,{}).get('items',0)>0 for k in ('recommend','search','bangumi')) and not result['unfinished'] and result['stock_hashes_unchanged'] and result['stock_processes_unchanged']
    print('RESULT='+repr(result))
    return 0 if result['passed'] else 1


if __name__=='__main__':sys.exit(main())
