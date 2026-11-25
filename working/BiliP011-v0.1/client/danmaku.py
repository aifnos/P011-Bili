"""Bounded, data-only legacy Bilibili danmaku normalization (Python 3.5).

Mode 7 is declarative animation, NOT code. Modes 8/code and 9/BAS are counted
but never executed or displayed as literal source. No fabricated merge counts.
"""
import json
import math
import re
import zlib


class InvalidDanmaku(ValueError): pass


def text_clean(value, limit=120, multiline=False):
    if not isinstance(value, str): return ''
    return ''.join(c if ord(c) >= 32 or (multiline and c == '\n') else ' ' for c in value)[:limit]


def number(value, low, high):
    if isinstance(value, bool): raise ValueError('boolean')
    result = float(value)
    if not math.isfinite(result) or not low <= result <= high: raise ValueError('range')
    return result


def advanced(text):
    # Format used by the upstream wiliwili DanmakuItem mode-7 reader. JSON is
    # parsed structurally so commas/quotes inside text cannot shift fields.
    if len(text) > 4096: raise ValueError('large animation')
    a = json.loads(text)
    if not isinstance(a, list) or not 5 <= len(a) <= 15: raise ValueError('shape')
    x, y = number(a[0], -2048, 4096), number(a[1], -2048, 4096)
    opacity = str(a[2]).split('-')
    if len(opacity) != 2: raise ValueError('alpha')
    life = number(a[3], .1, 20)
    message = text_clean(a[4], 160, True)
    if not message: raise ValueError('text')
    end_x = number(a[7], -2048, 4096) if len(a) > 7 else x
    end_y = number(a[8], -2048, 4096) if len(a) > 8 else y
    path = [[x, y], [end_x, end_y]]
    relative = all(0 <= v <= 1 for v in (x, y, end_x, end_y))
    if len(a) > 14 and a[14]:
        if not isinstance(a[14], str) or len(a[14]) > 2048: raise ValueError('path')
        parts = re.findall(r'[ML](-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)', a[14])
        if not 2 <= len(parts) <= 64: raise ValueError('path')
        if re.sub(r'[ML]-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?', '', a[14]).strip(): raise ValueError('path')
        path = [[number(px,-2048,4096),number(py,-2048,4096)] for px,py in parts]
        relative = False
    return {'text':message, 'life':life, 'alpha0':number(opacity[0],0,1), 'alpha1':number(opacity[1],0,1),
            'path':path, 'relative':relative,
            'rotate_z':number(a[5],-3600,3600) if len(a)>5 else 0,
            'rotate_y':number(a[6],-3600,3600) if len(a)>6 else 0,
            'move':number(a[9],0,20000)/1000 if len(a)>9 else life,
            'delay':number(a[10],0,20000)/1000 if len(a)>10 else 0,
            'outline':str(a[11]).lower() not in ('0','false') if len(a)>11 else True,
            'linear':str(a[13]).lower() not in ('0','false') if len(a)>13 else True}


def decode(raw):
    cap = 4*1024*1024
    if not isinstance(raw,bytes) or len(raw)>cap: raise InvalidDanmaku('size')
    decoded=raw
    if not raw.lstrip().startswith((b'<i',b'<?xml')):
        decoded=None
        for bits in (-15,15,31):
            try:
                inflater=zlib.decompressobj(bits);body=inflater.decompress(raw,cap+1)
                if len(body)>cap or not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:continue
                decoded=body;break
            except zlib.error:pass
        if decoded is None:raise InvalidDanmaku('compression')
    try:xml=decoded.decode('utf-8')
    except UnicodeError:raise InvalidDanmaku('encoding')
    if '<i>' not in xml or '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper():raise InvalidDanmaku('xml')
    rows=[];total=0;types={str(x):0 for x in range(1,10)};unsupported=0
    for match in re.finditer(r'<d\s+p="([^"<>]{1,256})"\s*>([^<]{0,8192})</d>',xml):
        total+=1
        fields=match.group(1).split(',')
        if len(fields)<4:continue
        try:t=number(fields[0],0,86400);mode=int(fields[1]);size=int(fields[2]);color=int(fields[3])
        except (ValueError,TypeError):continue
        if not 1<=mode<=9 or not 0<=color<=0xffffff or not 1<=size<=100:continue
        types[str(mode)]+=1
        if mode in (8,9):unsupported+=1;continue
        if len(rows)>=2000:continue
        text=match.group(2)
        # amp last prevents double-unescaping e.g. &amp;lt;.
        for src,dst in (('&lt;','<'),('&gt;','>'),('&quot;','"'),('&apos;',"'"),('&amp;','&')):text=text.replace(src,dst)
        def numeric(m):
            try:
                value=int(m.group(1)[1:],16) if m.group(1).startswith('x') else int(m.group(1))
                return chr(value) if 32<=value<=0x10ffff and not 0xd800<=value<=0xdfff else ' '
            except (ValueError,OverflowError):return ' '
        text=re.sub(r'&#(x[0-9A-Fa-f]{1,6}|[0-9]{1,7});',numeric,text)
        row={'time':t,'mode':mode,'color':color,'size':size}
        if mode==7:
            try:row['advanced']=advanced(text);row['text']=row['advanced']['text']
            except (ValueError,TypeError,OverflowError):unsupported+=1;continue
        else:row['text']=text_clean(text)
        if row['text']:rows.append(row)
    rows.sort(key=lambda r:r['time'])
    return {'items':rows,'truncated':total>len(rows),'types':types,'unsupported':unsupported,
            'source':'official-xml-pool','official_merge_count':False}
