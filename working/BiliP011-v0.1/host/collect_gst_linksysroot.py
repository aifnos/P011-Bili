"""Copy stock GStreamer link-only libraries and target GLib headers. Read-only."""
import datetime,hashlib,json
from probe_device import ROOT,BASE,NATIVE,Adb,result_from,archive


def main():
    out=ROOT/'logs'/('BiliP011-GstLinkSysroot-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
    dest=BASE/'private-gst-linksysroot';dest.mkdir(exist_ok=True)
    adb=Adb(out);safety=(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8')
    gate=safety+'\ns=stock_snapshot();require_stock(s);print("RESULT="+repr(s))'
    before=result_from(adb.python('before',gate))
    selected=result_from(adb.python('select',r'''
import os,glob,hashlib
paths=[]
for stem in ['gstreamer-1.0','gstapp-1.0','gstbase-1.0','gstvideo-1.0','gstaudio-1.0','gstpbutils-1.0','gstallocators-1.0','glib-2.0','gobject-2.0','gmodule-2.0','sprd_omx_core']:
 for p in sorted(glob.glob('/usr/lib/lib'+stem+'.so*')):
  if not os.path.islink(p):paths.append(p)
print('RESULT='+repr({'libraries':[{'path':p,'bytes':os.path.getsize(p),'sha256':hashlib.sha256(open(p,'rb').read()).hexdigest()} for p in paths]}))
'''))
    try:
        for row in selected['libraries']:
            target=dest/row['path'].lstrip('/');target.parent.mkdir(parents=True,exist_ok=True)
            if not target.exists():adb.run('pull-library',['pull',row['path'],str(target)])
            if len(target.read_bytes())!=row['bytes'] or hashlib.sha256(target.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Link library identity mismatch')
        for path in ['/usr/include/glib-2.0','/usr/lib/glib-2.0/include']:
            target=dest/path.lstrip('/');target.parent.mkdir(parents=True,exist_ok=True)
            if not target.exists():adb.run('pull-header',['pull',path,str(target)])
    finally:
        after=result_from(adb.python('after',gate))
        selected.update(stock_unchanged=before==after,device_writes=False,distribution='PRIVATE_LINK_ONLY_NO_VENDOR_BINARY_DISTRIBUTION')
        (dest/'manifest.json').write_text(json.dumps(selected,indent=2),encoding='utf-8')
        (out/'result.json').write_text(json.dumps(selected,indent=2),encoding='utf-8')
        print(json.dumps(selected,indent=2));print('LOG_DIR='+str(out));archive(out)


if __name__=='__main__':main()
