"""Pin and convert Apache-2.0 Rime/Android Pinyin dictionary, PC only.

The derived index changes only representation/order and caps candidates per
spelling. Source dictionary, license, authors and conversion lock are retained.
No fonts, executable code, personal history or network input suggestions.
"""
import collections
import hashlib
import json
import pathlib
import re
import urllib.request
import zlib
BASE=pathlib.Path(__file__).resolve().parents[1]
REV='0c6861ef7420ee780270ca6d993d18d4101049d0'
DEST=BASE/'client/deps/rime-pinyin-simp'
DEST.mkdir(parents=True,exist_ok=True)
lock={}
for name in ('pinyin_simp.dict.yaml','LICENSE','AUTHORS'):
    with urllib.request.urlopen('https://raw.githubusercontent.com/rime/rime-pinyin-simp/'+REV+'/'+name,timeout=30) as response:
        data=response.read(8*1024*1024+1)
    assert len(data)<=8*1024*1024
    path=DEST/name
    if path.exists() and path.read_bytes()!=data: raise ValueError('Pinned dictionary changed')
    if not path.exists():path.write_bytes(data)
    lock[name]=hashlib.sha256(data).hexdigest()
source=(DEST/'pinyin_simp.dict.yaml').read_text(encoding='utf-8')
rows=collections.defaultdict(list)
for line in source.split('...',1)[1].splitlines():
    if not line or line.startswith('#'):continue
    fields=line.split('\t')
    if len(fields)<2:continue
    word,spelling=fields[:2]
    spelling=spelling.replace(' ','').replace("'",'').replace('ü','v')
    if not re.fullmatch('[a-z]{1,48}',spelling) or len(word)>12:continue
    try:weight=float(fields[2].strip('%')) if len(fields)>2 else 1
    except ValueError:weight=1
    rows[spelling].append([word,weight])
index={}
for spelling,values in sorted(rows.items()):
    seen=set();result=[]
    for word,weight in sorted(values,key=lambda x:(-x[1],x[0])):
        if word in seen:continue
        seen.add(word);result.append([word,weight])
    index[spelling]=result[:60]
assert 'nihao' in index and 'dianying' in index and 'zhong' in index
packed=zlib.compress(json.dumps(index,ensure_ascii=False,separators=(',',':')).encode('utf-8'),9)
path=BASE/'client/deps/pinyin.json.z'
if path.exists() and path.read_bytes()!=packed:raise ValueError('Derived dictionary differs')
if not path.exists():path.write_bytes(packed)
lock.update(revision=REV,derived_sha256=hashlib.sha256(packed).hexdigest(),keys=len(index),bytes=len(packed))
record=BASE/'client/deps/pinyin-sources.json'
if record.exists() and json.loads(record.read_bytes())!=lock:raise ValueError('Dictionary lock differs')
record.write_text(json.dumps(lock,indent=2),encoding='utf-8')
print(json.dumps(lock,indent=2))
