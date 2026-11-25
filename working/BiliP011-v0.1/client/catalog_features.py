"""Python 3.5: bounded official library and timed-media data, private IPC only."""
import math
import re

OPS={'catalog_library','player_metadata','player_subtitle','player_preview'}
CATEGORIES=('watchlater','folders','folder','followings','up','popular','ranking','weekly','week','related','collection','my_bangumi','timeline','live_following')

def arguments(op,a,Failure):
    if not isinstance(a,dict):raise Failure('BAD_INPUT')
    out={}
    if op=='catalog_library':
        category=a.get('category')
        if category not in CATEGORIES:raise Failure('BAD_INPUT')
        page=a.get('page',1)
        if type(page) is not int or not 1<=page<=100:raise Failure('BAD_INPUT')
        out.update(category=category,page=page)
        keys=('id',) if category in ('folder','up','week') else ('bvid',) if category in ('related','collection') else ()
    else:keys=('bvid','cid','track') if op=='player_subtitle' else ('bvid','cid')
    for key in keys:
        value=a.get(key,'');pattern=r'BV[0-9A-Za-z]{10}$' if key=='bvid' else r'[0-9]{1,20}$'
        if not isinstance(value,str) or not re.match(pattern,value):raise Failure('BAD_INPUT')
        out[key]=value
    if op=='player_preview':
        if not finite(a.get('position')):raise Failure('BAD_INPUT')
        out['position']=a['position']
    return out

def finite(value,upper=604800):
    return type(value) in (int,float) and math.isfinite(value) and 0<=value<=upper

def dispatch(b,op,args,generation,Failure,short):
    data=b.helper(op,args)
    if generation!=b.qr_generation:raise Failure('CANCELED')
    if not isinstance(data,dict):raise Failure('API_SCHEMA')
    if getattr(b,'catalog_probe',False):
        key=args['category'] if op=='catalog_library' else op
        b.catalog_evidence[key]=dict(items=len(data.get('items',[])),tracks=len(data.get('tracks',[])),chapters=len(data.get('chapters',[])),cues=len(data.get('cues',[])),page=args.get('page',0),more=data.get('more') is True)
    if op=='player_preview':
        for k in ('x','y','w','h'):
            if type(data.get(k)) is not int or not 0<=data[k]<=4096:raise Failure('API_SCHEMA')
        raw=data.get('jpeg')
        if not isinstance(raw,str) or len(raw)>600000 or re.search(r'[^A-Za-z0-9+/=]',raw):raise Failure('API_SCHEMA')
        if not finite(data.get('start')) or not finite(data.get('end')) or data['end']<=data['start']:raise Failure('API_SCHEMA')
        return {k:data[k] for k in ('x','y','w','h','jpeg','start','end')}
    if op=='catalog_library':
        rows=data.get('items')
        if not isinstance(rows,list) or len(rows)>20:raise Failure('API_SCHEMA')
        clean=[]
        for r in rows:
            if not isinstance(r,dict):raise Failure('API_SCHEMA')
            row=b.card(r)
            for key in ('id','subtitle'):row[key]=short(r.get(key),180)
            row['playable']=bool(re.match(r'^BV[0-9A-Za-z]{10}$',row.get('bvid',''))) or bool(row.get('season') or row.get('ep') or row.get('room'))
            clean.append(row)
        return dict(items=clean,page=args['page'],more=data.get('more') is True,
                    title=short(data.get('title'),120),description=short(data.get('description'),240),following=data.get('following') is True)
    if op=='player_metadata':
        tracks=[];chapters=[]
        for r in data.get('tracks',[])[:32]:
            if isinstance(r,dict) and re.match(r'^[0-9]{1,20}$',str(r.get('id',''))):
                tracks.append(dict(id=r['id'],label=short(r.get('label'),80),language=short(r.get('language'),40),ai=r.get('ai') is True))
        for r in data.get('chapters',[])[:200]:
            if isinstance(r,dict) and finite(r.get('start')) and finite(r.get('end')) and r['end']>r['start']:
                chapters.append(dict(start=r['start'],end=r['end'],title=short(r.get('title'),180)))
        return dict(tracks=tracks,chapters=sorted(chapters,key=lambda x:x['start']))
    cues=data.get('cues',[])
    if not isinstance(cues,list) or len(cues)>12000:raise Failure('API_SCHEMA')
    result=[];size=0
    for r in cues:
        if not isinstance(r,dict) or not finite(r.get('start')) or not finite(r.get('end')) or r['end']<=r['start']:continue
        text=short(r.get('text'),400);size+=len(text.encode('utf-8'))
        if size>500000:raise Failure('RESOURCE_LIMIT')
        result.append(dict(start=r['start'],end=r['end'],text=text))
    return dict(cues=sorted(result,key=lambda x:x['start']),track=args['track'])
