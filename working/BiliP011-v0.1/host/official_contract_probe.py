"""Read-only primary-source capture. No login, cookies or account mutations."""
import datetime,gzip,hashlib,json,pathlib,re,urllib.request,urllib.parse
from build_awake_trial import ROOT

PAGES=('https://www.bilibili.com/video/BV1gi4y1V7Xx','https://passport.bilibili.com/login','https://live.bilibili.com/','https://www.bilibili.com/account/history','https://www.bilibili.com/')
PATTERN=re.compile(r"[^\n]{0,140}(?:archive/like|archive/has/like|archive/relation|archive/like/triple|coin/add|fav/resource/deal|folder/created/list|history/cursor|history/toview|passport-login|dislike|feedback|listen/|playurl)[^\n]{0,260}",re.I)

def fetch(url):
    parts=urllib.parse.urlsplit(url);host=parts.hostname or ''
    if parts.scheme!='https' or not any(host==d or host.endswith('.'+d) for d in ('bilibili.com','hdslb.com')):raise ValueError('Non-official source')
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.bilibili.com/'})
    with urllib.request.urlopen(req,timeout=18) as response:
        body=response.read(12*1024*1024+1)
        if len(body)>12*1024*1024:raise ValueError('Source too large')
        if body.startswith(b'\x1f\x8b'):body=gzip.decompress(body)
        if len(body)>12*1024*1024:raise ValueError('Decoded source too large')
        return body

def main():
    out=ROOT/'logs'/('BiliP011-OfficialContracts-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
    print('LOG_DIR='+str(out),flush=True);queue=list(PAGES);seen=set();records=[];snippets=[]
    while queue and len(seen)<36:
        url=queue.pop(0)
        if url in seen:continue
        seen.add(url);row={'url':url}
        try:
            body=fetch(url);text=body.decode('utf-8','replace');key=hashlib.sha256(body).hexdigest()
            name=('%02d-'%len(records))+key[:12]+('.html' if url in PAGES else '.js');(out/name).write_bytes(body)
            row.update(file=name,sha256=key,bytes=len(body));hits=PATTERN.findall(text)
            row['contract_hits']=len(hits)
            for hit in hits[:80]:snippets.append({'file':name,'context':hit})
            if url in PAGES:
                scripts=re.findall(r'<script[^>]+src=[\"\x27]([^\"\x27]+)',text)
                row['scripts']=scripts
                for script in scripts[:16]:queue.append(urllib.parse.urljoin(url,script))
            elif '/assets/' in url:
                imports=re.findall(r'(?:from|import)\s*[\"\x27](\./[^\"\x27]+\.js)[\"\x27]',text)
                for child in imports[:8]:queue.append(urllib.parse.urljoin(url,child))
        except Exception as exc:row['error']=type(exc).__name__
        records.append(row);print(json.dumps({k:v for k,v in row.items() if k!='scripts'},ensure_ascii=False),flush=True)
    (out/'sources.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'contracts.json').write_text(json.dumps(snippets,ensure_ascii=False,indent=2),encoding='utf-8')
    print('READ_ONLY_NO_ACCOUNT_WRITES=True')

if __name__=='__main__':main()
