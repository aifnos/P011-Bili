"""Read actual authorized qualities for the fixed public benchmark; no player."""
import argparse,datetime,json,pathlib,re
from awake_trial import Adb,check_bundle,result_from,ROOT,archive
p=argparse.ArgumentParser();p.add_argument('--bundle',type=pathlib.Path,required=True);p.add_argument('--bvid',default='BV1Da411Y7U4');args=p.parse_args()
if not re.fullmatch('BV[0-9A-Za-z]{10}',args.bvid):raise ValueError('Invalid public sample ID')
meta,_=check_bundle(args.bundle);out=ROOT/'logs'/('BiliP011-QualityInventory-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir();adb=Adb(out)
code='ROOT='+repr(meta['remote'])+'\nBV='+repr(args.bvid)+'\n'+r'''
import os,sys
sys.path.insert(0,ROOT)
import service,config,awake_trial as trial
from native_safety import stock_snapshot,require_stock
trial.verify();before=stock_snapshot();require_stock(before)
b=service.Backend(ROOT,config.MEDIA+'/bin/bili-api','','/mnt/data/p011-toolbox/bili-account',dict(os.environ,LD_LIBRARY_PATH=config.MEDIA+'/lib'),lifetime=50)
try:
 d=b.helper('detail',{'kind':'video','bvid':BV})
 row=d['parts'][0];row['quality']=0
 q=b.helper('qualities',service.safe_args('qualities',row))
 report={'items':q['items'],'codecs':q['codecs'],'variants':q.get('variants',[]),'account_content_exported':False,'playback_started':False}
finally:b.close()
after=stock_snapshot();require_stock(after);report['stock_unchanged']=before==after
print('RESULT='+ascii(report))
'''
report=result_from(adb.python('authorized-quality-metadata',code,timeout=65))
(out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,indent=2));print('LOG_DIR='+str(out));archive(out)
