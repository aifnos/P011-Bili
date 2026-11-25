"""Follow observed official public chunks; no login or state-changing calls."""
import datetime,hashlib,json,re,urllib.parse
from official_contract_probe import fetch
from build_awake_trial import ROOT

def main():
    source=ROOT/'logs/BiliP011-OfficialContracts-20260926-165730'
    out=ROOT/'logs'/('BiliP011-OfficialFeatureSources-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
    print('LOG_DIR='+str(out),flush=True)
    passport=(source/'15-411354a4148c.js').read_text(encoding='utf-8')
    hashes=re.search(r'263:"[a-f0-9]+"',passport)
    # Exact filenames observed in the official bundle's lazy-chunk manifest.
    mapping=re.search(r's\.u=e=>"static/js/async/"\+e\+"\."\+\(\{([^}]+)',passport).group(1)
    queue=['https://s1.hdslb.com/bfs/static/2233-monorepo/passport/static/js/async/'+i+'.'+h+'.js' for i,h in re.findall(r'(\d+):"([a-f0-9]+)"',mapping)]
    queue+=['https://s1.hdslb.com/bfs/static/fenice/home/client/home/assets/App.04c3739b.js']
    page=(source/'00-d182b65d056d.html').read_text(encoding='utf-8')
    inserted=re.search(r'"insertScripts":(\[[^\]]+\])',page)
    if inserted:
        queue[:0]=[urllib.parse.urljoin('https://www.bilibili.com/',u) for u in json.loads(inserted.group(1))]
    for value in re.findall(r'["\x27]((?://|https://)[^"\x27\s]+)["\x27]',page):
        if 'jinkela' in value and ('.js' in value or 'video' in value):queue.append(urllib.parse.urljoin('https://www.bilibili.com/',value))
    records=[];seen=set()
    while queue and len(seen)<24:
        url=queue.pop(0)
        if url in seen:continue
        seen.add(url);row={'url':url}
        try:
            body=fetch(url);key=hashlib.sha256(body).hexdigest();name='%02d-%s.js'%(len(records),key[:12]);(out/name).write_bytes(body)
            row.update(file=name,sha256=key,bytes=len(body));text=body.decode('utf-8','replace')
            if '/assets/' in url:
                for child in re.findall(r'["\x27](\./[^"\x27]+\.js)["\x27]',text)[:6]:queue.append(urllib.parse.urljoin(url,child))
        except Exception as exc:row['error']=type(exc).__name__
        records.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    (out/'sources.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    print('READ_ONLY_NO_ACCOUNT_WRITES=True')

if __name__=='__main__':main()
