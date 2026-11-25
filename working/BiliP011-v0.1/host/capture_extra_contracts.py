"""Official public bundles only, no account cookies or write requests."""
import datetime,hashlib,json,re,urllib.parse
from official_contract_probe import fetch
from build_awake_trial import ROOT

def main():
    out=ROOT/'logs'/('BiliP011-ExtraContracts-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir();print('LOG_DIR='+str(out),flush=True)
    queue=['https://live.bilibili.com/6','https://www.bilibili.com/bangumi/play/ss41410','https://s1.hdslb.com/bfs/seed/jinkela/commentpc/bili-comments.js','https://s1.hdslb.com/bfs/seed/jinkela/commentpc/new-comment.min.js'];seen=set();records=[];hits=[]
    needles=('protover','getDanmuInfo','/x/v2/reply/add','/x/v2/reply/action','/pgc/web/follow/add','/pgc/web/follow/del','wss://','heartbeatInterval','/x/v2/dm/post')
    while queue and len(seen)<24:
        url=queue.pop(0)
        if url in seen:continue
        seen.add(url);r={'url':url}
        try:
            raw=fetch(url);s=raw.decode('utf-8','replace');digest=hashlib.sha256(raw).hexdigest();name='%02d-%s.txt'%(len(records),digest[:12]);(out/name).write_bytes(raw);r.update(file=name,sha256=digest,bytes=len(raw))
            if len(records)<2:
                scripts=[next(v for v in match if v) for match in re.findall(r'<script\b[^>]*\bsrc\s*=\s*(?:"([^"]+)"|\x27([^\x27]+)\x27|([^\s>]+))',s,re.I)]
                for child in scripts:queue.append(urllib.parse.urljoin(url,child))
                r['scripts']=scripts
            for needle in needles:
                at=s.find(needle)
                if at>=0:hits.append(dict(file=name,term=needle,excerpt=s[max(0,at-100):at+400]))
        except Exception as e:r['error']=type(e).__name__
        records.append(r)
    (out/'sources.json').write_text(json.dumps(records,indent=2),encoding='utf-8');(out/'contracts.json').write_text(json.dumps(hits,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'sources':len(records),'hits':hits},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
