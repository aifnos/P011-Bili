"""Read-only, bounded observation of the existing P011 scene governor.

Values stay in the driver's raw units. A zero response may be an unavailable
query, not a measured zero clock or proof that a feature is disabled.
"""
import datetime
import hashlib
import inspect
import json
import zipfile


def read_ddr_state(detailed=False):
    # Self-contained Python 3.5 function embedded in the existing ADB helper.
    import re
    import time
    began=time.monotonic()
    base='/sys/class/devfreq/scene-frequency/'
    paths={'reported_current_raw':'sprd-governor/ddrinfo_cur_freq',
           'ap_vote_raw':'sprd-governor/ddrinfo_ap_freq',
           'cp_vote_raw':'sprd-governor/ddrinfo_cp_freq',
           'generic_current_raw':'cur_freq'}
    if detailed:
        paths.update({'dfs_status_raw':'sprd-governor/dfs_on_off',
                      'auto_dfs_status_raw':'sprd-governor/auto_dfs_on_off',
                      'minimum_raw':'min_freq','maximum_raw':'max_freq',
                      'frequency_table_raw':'sprd-governor/ddrinfo_freq_table',
                      'scenes':'sprd-governor/scene_dfs_list'})
    result={'values':{},'errors':{},'units':'driver_raw_not_converted'}
    def number(raw):
        if not re.match(r'^[0-9]{1,10}$',raw) or int(raw)>4294967295:raise ValueError('Invalid unsigned value')
        return int(raw)
    for key,suffix in sorted(paths.items()):
        try:
            with open(base+suffix,'r') as stream:raw=stream.read(4097)
            if len(raw)>4096:raise ValueError('Oversized attribute')
            if key=='frequency_table_raw':
                cells=raw.split()
                if not 1<=len(cells)<=32:raise ValueError('Invalid table length')
                value=[number(cell) for cell in cells]
            elif key=='scenes':
                value={}
                for line in raw.splitlines():
                    match=re.match(r'^(boost|lcdon|lcdoff|camlow|camhigh) freq ([0-9]{1,10})  magic 0x[0-9a-fA-F]{1,8} count ([0-9]{1,10})$',line)
                    if not match or match.group(1) in value:raise ValueError('Unexpected scene record')
                    value[match.group(1)]={'frequency_raw':number(match.group(2)),'count':number(match.group(3))}
                if not value:raise ValueError('Empty scene records')
            else:value=number(raw.strip())
            result['values'][key]=value
        except OSError as error:result['errors'][key]={'kind':'io','errno':error.errno}
        except (ValueError,UnicodeError):result['errors'][key]={'kind':'format'}
    result['captured_at']=time.monotonic()
    result['read_duration_ms']=round((result['captured_at']-began)*1000,3)
    return result


def summarize_ddr(samples):
    groups={'playing':[],'paused':[]}
    for a,b in zip(samples,samples[1:]):
        pa,pb=a.get('process'),b.get('process');sa,sb=a.get('player',{}),b.get('player',{})
        if not pa or not pb or (pa['pid'],pa['start'])!=(pb['pid'],pb['start']) or not 0<b['time']-a['time']<6:continue
        if any(s.get('loaded') is not True or s.get('switch_pending') is True or
               type(s.get('position')) not in (int,float) or not 6<=s['position']<86400 for s in (sa,sb)):continue
        key='paused' if all(s.get('paused') is True and s.get('active') is False for s in (sa,sb)) else \
            'playing' if all(s.get('active') is True and s.get('paused') is False for s in (sa,sb)) else None
        if key:groups[key].append(b.get('ddr',{}))
    result={}
    for key,rows in groups.items():
        hist={};valid=0
        for row in rows:
            value=row.get('values',{}).get('reported_current_raw')
            if type(value) is int and 0<value<=4294967295 and not row.get('errors'):
                valid+=1;hist[str(value)]=hist.get(str(value),0)+1
        duration=[row['read_duration_ms'] for row in rows if type(row.get('read_duration_ms')) in (int,float) and 0<=row['read_duration_ms']<10000]
        result[key]={'samples':len(rows),'valid_current_samples':valid,'reported_current_histogram_raw':hist,
                     'maximum_read_ms':max(duration) if duration else None}
    result['observed']=all(result[key]['valid_current_samples']==result[key]['samples']>=minimum and
                           result[key]['maximum_read_ms'] is not None for key,minimum in (('playing',5),('paused',3)))
    result.update(units='driver_raw_not_converted',causal_performance_result=False,frequency_changed=False)
    return result


def main():
    from awake_trial import Adb,ROOT,NATIVE,result_from
    from ion_copy_trial import IDLE_GATE
    out=ROOT/'logs'/('BiliP011-DDRReadonly-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir();print('LOG_DIR='+str(out),flush=True)
    source=(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8')+'\n'+IDLE_GATE+'\n'+inspect.getsource(read_ddr_state)+r'''
before=stock_snapshot();require_stock(before);require_private_idle()
report=read_ddr_state(True)
after=stock_snapshot();require_stock(after);require_private_idle()
report.update(stock_unchanged=before==after,frequency_changed=False,performance_improvement_proven=False)
report['passed']=report['stock_unchanged'] and not report['errors'] and report['values'].get('reported_current_raw',0)>0
print('RESULT='+repr(report))
'''
    report=result_from(Adb(out).python('read-only-scene-governor',source))
    body=json.dumps(report,indent=2).encode('ascii');(out/'result.json').write_bytes(body)
    archive=out.with_name(out.name+'-safe.zip')
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        z.writestr('result.json',body);z.writestr('SHA256.json',json.dumps({'result.json':hashlib.sha256(body).hexdigest()}))
    with zipfile.ZipFile(archive) as z:
        if z.testzip() or hashlib.sha256(z.read('result.json')).hexdigest()!=json.loads(z.read('SHA256.json'))['result.json']:
            raise ValueError('Archive integrity failed')
    print(json.dumps(report,indent=2));print('RESULT_ZIP='+str(archive))
    print('ZIP_SHA256='+hashlib.sha256(archive.read_bytes()).hexdigest())
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
