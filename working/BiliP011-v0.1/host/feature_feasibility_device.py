"""Read-only GET feasibility checks; executed in memory, Python 3.5 compatible.

No product feature implementation. Never export cookies, IDs, names, URLs,
subtitle text, folder contents, history contents, or raw server responses.
"""
import hashlib
import os
import signal
import subprocess
import sys
import time
import urllib.parse

signal.alarm(165)
for filename, expected in VERIFIED_FILES.items():
    path = RUNTIME + '/' + filename
    if os.path.islink(path):
        raise RuntimeError('Linked runtime dependency')
    with open(path, 'rb') as handle:
        if hashlib.sha256(handle.read()).hexdigest() != expected:
            raise RuntimeError('Runtime dependency changed')
sys.path[:0] = [RUNTIME + '/stdlib-json35.zip', RUNTIME]
import json
from native_safety import stock_snapshot, require_stock

before = stock_snapshot()
require_stock(before)
cookie = '/mnt/data/p011-toolbox/bili-account/cookies.txt'
if os.path.islink(cookie):
    raise RuntimeError('Linked account file')
def cookie_hash():
    if not os.path.isfile(cookie):
        return None
    with open(cookie, 'rb') as handle:
        return hashlib.sha256(handle.read(65537)).hexdigest()
original_cookie = cookie_hash()
env = dict(os.environ)
for key in ('http_proxy','https_proxy','all_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','LD_PRELOAD'):
    env.pop(key, None)
report = {'group': GROUP, 'checks': {}, 'account_writes': False,
          'device_files_written': False, 'player_started': False}
checks = report['checks']
nav = None
def req(name, path, params=None, auth=False, signed=False, live=False):
    global nav
    params = dict(params or {})
    if not path.startswith('/') or '?' in path or '\n' in path:
        raise ValueError('Invalid fixed API path')
    if signed:
        if nav is None:
            nav = req('wbi_keys', '/x/web-interface/nav', auth=auth)
        images = nav.get('wbi_img') or {}
        raw = ''.join(images.get(k, '').rsplit('/',1)[-1].split('.')[0] for k in ('img_url','sub_url'))
        if len(raw) != 64:
            checks[name] = {'skipped': 'WBI_KEYS_UNAVAILABLE'}
            return {}
        permutation = [46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,27,43,5,49,33,9,42,19,29,28,14,39,12,38,41,13]
        mixin = ''.join(raw[i] for i in permutation)
        params['wts'] = str(int(time.time()))
        params = {k: ''.join(c for c in str(v) if c not in "!'()*") for k,v in params.items()}
        query = urllib.parse.urlencode(sorted(params.items()))
        params['w_rid'] = hashlib.md5((query+mixin).encode()).hexdigest()
    url = ('https://api.live.bilibili.com' if live else 'https://api.bilibili.com') + path
    if params:
        url += '?' + urllib.parse.urlencode(sorted(params.items()))
    command = ['curl','--silent','--show-error','--connect-timeout','5','--max-time','12',
               '--max-filesize','2097152','--proto','=https','--noproxy','*',
               '-A','wiliwili','-e','https://www.bilibili.com/client','-w','\n%{http_code}']
    if auth and original_cookie:
        command += ['--cookie', cookie]
    started = time.monotonic()
    proc = subprocess.Popen(command+[url], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    try:
        out, err = proc.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill();out,err = proc.communicate()
    entry = {'transport_exit': proc.returncode, 'elapsed_ms': int((time.monotonic()-started)*1000)}
    checks[name] = entry
    try:
        body, status = out.rsplit(b'\n',1)
        entry['http'] = int(status)
        if len(body)>2097152:
            raise ValueError('Oversized response')
        root = json.loads(body.decode('utf-8'))
        entry['code'] = root.get('code')
        entry['ok'] = entry['http']==200 and root.get('code')==0
        data = root.get('data') if root.get('data') is not None else root.get('result')
        return data or {}
    except (ValueError, TypeError, AttributeError):
        entry['ok'] = False
        entry['json_valid'] = False
        return {}

def rows(name, values):
    values = values if isinstance(values,list) else []
    checks[name]['items'] = len(values)
    checks[name]['video_items'] = sum(isinstance(v,dict) and bool(v.get('bvid')) for v in values)
    return values

try:
    if GROUP == 'public':
        d = req('popular', '/x/web-interface/popular', {'ps':3,'pn':1})
        items = rows('popular',d.get('list'))
        d = req('weekly_index','/x/web-interface/popular/series/list')
        weeks = rows('weekly_index',d.get('list'))
        if weeks:
            d = req('weekly_videos','/x/web-interface/popular/series/one',{'number':weeks[0]['number']})
            rows('weekly_videos',d.get('list'))
        d = req('ranking','/x/web-interface/ranking/v2',{'rid':0,'type':'all'})
        rows('ranking',d.get('list'))
        d = req('related','/x/web-interface/archive/related',{'bvid':'BV1Da411Y7U4'})
        rows('related',d)
        d = req('timeline','/pgc/web/timeline/v2',{'types':1,'before':0,'after':6})
        days = d if isinstance(d,list) else []
        checks['timeline']['days'] = len(days)
        checks['timeline']['episodes'] = sum(len(v.get('episodes',[])) for v in days)
        candidate = items[0].get('bvid') if items else 'BV1Da411Y7U4'
        detail = req('public_detail','/x/web-interface/view',{'bvid':candidate})
        season = detail.get('ugc_season') or {}
        sections = season.get('sections') or []
        checks['public_detail']['collection_episodes'] = sum(len(s.get('episodes',[])) for s in sections)
        owner = detail.get('owner') or {}
        if owner.get('mid'):
            d = req('up_profile','/x/space/wbi/acc/info',{'mid':owner['mid']},signed=True)
            checks['up_profile']['profile_shape'] = bool(d.get('mid') and d.get('name'))
            d = req('up_uploads','/x/space/wbi/arc/search',{'mid':owner['mid'],'pn':1,'ps':5,'order':'pubdate'},signed=True)
            rows('up_uploads',(d.get('list') or {}).get('vlist'))
    elif GROUP == 'account':
        nav = req('account_nav','/x/web-interface/nav',auth=True)
        report['logged_in'] = nav.get('isLogin') is True
        if report['logged_in']:
            d = req('watchlater','/x/v2/history/toview/web',auth=True)
            rows('watchlater',d.get('list'))
            d = req('folders','/x/v3/fav/folder/created/list-all',{'up_mid':nav['mid']},auth=True)
            folders = rows('folders',d.get('list'))
            nonempty = [f for f in folders if f.get('media_count',0)>0]
            if nonempty:
                d = req('folder_videos','/x/v3/fav/resource/list',{'media_id':nonempty[0]['id'],'pn':1,'ps':5,'platform':'web'},auth=True)
                rows('folder_videos',d.get('medias'))
                checks['folder_videos']['has_more'] = bool(d.get('has_more'))
            d = req('my_bangumi','/x/space/bangumi/follow/list',{'vmid':nav['mid'],'pn':1,'ps':5,'type':1},auth=True)
            rows('my_bangumi',d.get('list'))
            d = req('followings','/x/relation/followings',{'vmid':nav['mid'],'pn':1,'ps':5},auth=True)
            rows('followings',d.get('list'))
            d = req('cloud_history','/x/web-interface/history/cursor',{'ps':5,'type':'all'},auth=True)
            history = rows('cloud_history',d.get('list'))
            checks['cloud_history']['with_progress'] = sum(isinstance(v.get('progress'),int) for v in history)
            checks['cloud_history']['with_part_cid'] = sum(bool((v.get('history') or {}).get('cid')) for v in history)
    elif GROUP == 'media':
        nav = req('account_nav','/x/web-interface/nav',auth=True)
        report['logged_in'] = nav.get('isLogin') is True
        # Public samples only; nothing selected from account history.
        for index,bvid in enumerate(('BV1Da411Y7U4','BV1Jt411P77c')):
            key = 'sample'+str(index)
            d = req(key+'_detail','/x/web-interface/view',{'bvid':bvid},auth=True)
            parts = d.get('pages') or []
            if not parts:
                continue
            part = parts[min(index,len(parts)-1)]
            params = {'bvid':bvid,'cid':part['cid']}
            info = req(key+'_player','/x/player/wbi/v2',params,auth=True,signed=True)
            subtitles = (info.get('subtitle') or {}).get('subtitles') or []
            checks[key+'_player']['subtitle_tracks'] = len(subtitles)
            checks[key+'_player']['subtitle_urls_valid'] = all(str(s.get('subtitle_url','')).startswith(('https://','//')) for s in subtitles)
            checks[key+'_player']['view_points'] = len(info.get('view_points') or [])
            d = req(key+'_preview','/x/player/videoshot',dict(params,index=1),auth=True)
            checks[key+'_preview']['sheets'] = len(d.get('image') or [])
            checks[key+'_preview']['time_points'] = len(d.get('index') or [])
        # Read-only plugin inventory, no pipeline and no decoding.
        for feature in ('scaletempo','pitch'):
            p = subprocess.Popen(['gst-inspect-1.0',feature],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
            try:
                output,error=p.communicate(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill();output,error=p.communicate()
            checks['plugin_'+feature]={'exit':p.returncode,'present':p.returncode==0}
    elif GROUP == 'live':
        d = req('live_following','/xlive/web-ucenter/v1/xfetter/GetWebList',{'page':1,'page_size':5},auth=True,live=True)
        rows('live_following',d.get('list'))
        d = req('live_home','/xlive/web-interface/v1/index/getList',{'platform':'web'},live=True)
        rooms = []
        def walk(value):
            if isinstance(value,dict):
                room = value.get('roomid') or value.get('room_id')
                if room and str(room).isdigit():rooms.append(str(room))
                for child in value.values():walk(child)
            elif isinstance(value,list):
                for child in value:walk(child)
        walk(d)
        checks['live_home']['rooms'] = len(set(rooms))
        if rooms:
            d = req('live_danmaku_info','/xlive/web-room/v1/index/getDanmuInfo',{'id':rooms[0],'type':0},auth=True,signed=True,live=True)
            checks['live_danmaku_info']['has_token'] = bool(d.get('token'))
            checks['live_danmaku_info']['servers'] = len(d.get('host_list') or [])
            checks['live_danmaku_info']['wss_ports'] = [h.get('wss_port') for h in d.get('host_list',[]) if type(h.get('wss_port')) in (str,int)]
            checks['live_danmaku_info']['official_chat_suffix'] = [str(h.get('host','')).endswith('.chat.bilibili.com') for h in d.get('host_list',[])]
            d = req('live_history_dm','/xlive/web-room/v1/dM/gethistory',{'roomid':rooms[0]},auth=True,live=True)
            checks['live_history_dm']['messages'] = len(d.get('room') or [])
    elif GROUP == 'followup':
        nav = req('account_nav','/x/web-interface/nav',auth=True)
        report['logged_in'] = nav.get('isLogin') is True
        # Correct route/parameters observed in the official timeline bundle.
        d = req('timeline_official','/pgc/web/timeline',{'types':1,'before':6,'after':6},auth=True)
        days = d if isinstance(d,list) else []
        checks['timeline_official']['days'] = len(days)
        checks['timeline_official']['episodes'] = sum(len(v.get('episodes',[])) for v in days)
        d = req('weekly_index','/x/web-interface/popular/series/list',auth=True)
        weeks = d.get('list') or []
        if weeks:
            d = req('weekly_authenticated','/x/web-interface/popular/series/one',{'number':weeks[0]['number']},auth=True,signed=True)
            rows('weekly_authenticated',d.get('list'))
    elif GROUP == 'subtitles':
        nav=req('account_nav','/x/web-interface/nav',auth=True)
        params={'bvid':'BV1Jt411P77c'}
        d=req('subtitle_sample','/x/web-interface/view',params,auth=True)
        parts=d.get('pages') or []
        if parts:
            params['cid']=parts[min(1,len(parts)-1)]['cid']
            d=req('subtitle_metadata','/x/player/wbi/v2',params,auth=True,signed=True)
            subs=(d.get('subtitle') or {}).get('subtitles') or []
            if subs:
                url=subs[0].get('subtitle_url','')
                if url.startswith('//'):url='https:'+url
                parsed=urllib.parse.urlsplit(url)
                if parsed.scheme=='https' and (parsed.hostname or '').endswith('.hdslb.com'):
                    command=['curl','--silent','--show-error','--connect-timeout','5','--max-time','12','--max-filesize','1048576','--proto','=https','--noproxy','*',url]
                    p=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
                    out,err=p.communicate(timeout=15)
                    value=json.loads(out.decode('utf-8'));segments=value.get('body') or []
                    checks['subtitle_body']={'exit':p.returncode,'segments':len(segments),'timed_text_valid':bool(segments) and all(isinstance(v.get('content'),str) and isinstance(v.get('from'),(int,float)) and isinstance(v.get('to'),(int,float)) and v['to']>=v['from'] for v in segments)}
    elif GROUP == 'pagination':
        nav=req('account_nav','/x/web-interface/nav',auth=True)
        report['logged_in']=nav.get('isLogin') is True
        if report['logged_in']:
            d=req('folders','/x/v3/fav/folder/created/list-all',{'up_mid':nav['mid']},auth=True)
            folders=[f for f in (d.get('list') or []) if f.get('media_count',0)>5]
            if folders:
                args={'media_id':folders[0]['id'],'ps':5,'platform':'web'}
                seen=[]
                for page in (1,2):
                    name='folder_page'+str(page)
                    d=req(name,'/x/v3/fav/resource/list',dict(args,pn=page),auth=True)
                    values=rows(name,d.get('medias'));seen.append(set(v.get('bvid') for v in values if v.get('bvid')))
                checks['folder_page2']['distinct_from_page1']=bool(seen[1]) and not bool(seen[0]&seen[1])
        # Only public content; verify chapter payloads without exporting text.
        d=req('chapter_sample','/x/web-interface/view',{'bvid':'BV1seYteFEvy'},auth=True)
        if d.get('cid'):
            d=req('chapter_metadata','/x/player/wbi/v2',{'bvid':'BV1seYteFEvy','cid':d['cid']},auth=True,signed=True)
            points=d.get('view_points') or []
            checks['chapter_metadata']['points']=len(points)
            checks['chapter_metadata']['time_fields']=bool(points) and all(isinstance(v.get('from'),(int,float)) and isinstance(v.get('to'),(int,float)) for v in points)
    else:
        raise ValueError('Unknown read-only group')
finally:
    after = stock_snapshot()
    require_stock(after)
    report['stock_unchanged'] = before == after
    report['credentials_unchanged'] = original_cookie == cookie_hash()
print('RESULT='+repr(report))
