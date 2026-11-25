"""Read only three VSP device-tree properties; never request a driver clock."""
import datetime,hashlib,inspect,json,re,struct


def decode_properties(properties):
    names=('compatible','clock-names','clocks')
    if set(properties)!=set(names):raise ValueError('Unexpected clock properties')
    if any(type(value) is not bytes or not 0<len(value)<=1024 for value in properties.values()):
        raise ValueError('Unbounded clock properties')
    def strings(raw):
        if not raw.endswith(b'\0'):raise ValueError('Unterminated clock strings')
        values=raw[:-1].decode('ascii').split('\0')
        if any(not re.fullmatch('[A-Za-z0-9_,.+-]{1,64}',value) for value in values):
            raise ValueError('Unexpected clock name')
        return values
    compatible=strings(properties['compatible']);names=strings(properties['clock-names'])
    raw=properties['clocks']
    if len(raw)%4 or len(names)>32:raise ValueError('Invalid clock cells')
    return dict(compatible=compatible,clock_names=names,source_names=[name for name in names if name.startswith('clk_src_')],
                raw_clock_cells=list(struct.unpack('>'+str(len(raw)//4)+'I',raw)),
                property_sha256={name:hashlib.sha256(value).hexdigest() for name,value in properties.items()},
                clock_specifiers_decoded=False,actual_clock_measured=False,frequency_changed=False)


PROBE=r'''
import re,struct
before=stock_snapshot();require_stock(before);require_private_idle()
node='/proc/device-tree/soc/ap-ahb/video-codec@21900000'
properties={name:open(node+'/'+name,'rb').read(1025) for name in ('compatible','clock-names','clocks')}
report=decode_properties(properties)
if report['compatible']!=['sprd,sharkle-vsp']:raise ValueError('Different VSP binding')
after=stock_snapshot();require_stock(after);require_private_idle()
report['stock_unchanged']=before==after
report['passed']=report['stock_unchanged']
print('RESULT='+repr(report))
'''


def main():
    from awake_trial import Adb,ROOT,NATIVE,result_from
    from ion_copy_trial import IDLE_GATE
    out=ROOT/'logs'/('BiliP011-VspClockTree-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir();print('LOG_DIR='+str(out),flush=True)
    source=(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8')+'\n'+IDLE_GATE+'\n'+inspect.getsource(decode_properties)+'\n'+PROBE
    result=result_from(Adb(out).python('read-only-clock-tree',source))
    (out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
    if result['passed'] is not True:raise ValueError('Stock changed during read-only query')


if __name__=='__main__':main()
