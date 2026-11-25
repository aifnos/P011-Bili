"""Read-only Qt automation/capture capability probe, without starting a UI."""
import argparse,datetime,json,pathlib
from awake_trial import ROOT,Adb,result_from,check_bundle,archive

def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=pathlib.Path,required=True);a=p.parse_args()
    meta,_=check_bundle(a.bundle)
    out=ROOT/'logs'/('BiliP011-UI-Environment-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
    code='ROOT='+repr(meta['remote'])+r'''
import sys,os,glob,signal
sys.path.insert(0,ROOT)
import awake_trial as trial
from native_safety import stock_snapshot,require_stock
signal.alarm(20);trial.verify();before=stock_snapshot();require_stock(before)
paths=[]
for pattern in ('/usr/lib/qt5/qml/QtTest/qmldir','/usr/lib/qt5/qml/QtTest/*.so',
 '/usr/lib/qt5/bin/qmltestrunner','/usr/bin/qmltestrunner',
 '/usr/lib/libQt5QuickTest.so*','/usr/lib/libQt5Test.so*','/usr/bin/weston-screenshooter'):
 paths.extend(glob.glob(pattern))
after=stock_snapshot();require_stock(after)
print('RESULT='+repr({'stock_unchanged':before==after,'paths':sorted(set(paths)),
 'window_opened':False,'account_used':False,'screen_captured':False}))
'''
    report=result_from(Adb(out).python('readonly-ui-environment',code,timeout=30))
    (out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2));archive(out)
    if not report.get('stock_unchanged'):raise SystemExit(1)

if __name__=='__main__':main()
