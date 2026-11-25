"""PC-only, immutable numerical evidence ZIP for the 2026-09-25 ION study."""
import collections,datetime,hashlib,json,pathlib,zipfile

ROOT=pathlib.Path(__file__).resolve().parents[3]
def main():
    names=('BiliP011-IONCopy-20260925-071358','BiliP011-HardwareSeek-20260925-072156',
           'BiliP011-HardwareSeek-20260925-072420','BiliP011-VendorAVC-ReadOnly-20260925-065838',
           'BiliP011-StockRestoreAudit-20260925-072555')
    files={};results=[]
    for name in names:
        path=ROOT/'logs'/name/'result.json'
        if path.is_symlink() or not path.is_file():raise ValueError('Missing original evidence')
        body=path.read_bytes();files[name+'/result.json']=body;results.append(json.loads(body))
    synthetic,normal,high,vendor,stock=results
    if any(row.get('passed') is not True for row in (synthetic,normal,high,stock)):raise ValueError('A required gate failed')
    if synthetic['playback_passed'] is not False or synthetic['probe']['video_decoded'] or high['playback_rate_passed'] is not False:raise ValueError('Evidence scope differs')
    if stock['active_private_processes']!=0 or vendor['stock_unchanged'] is not True or vendor['redistributable'] is not False:raise ValueError('Stock/vendor evidence differs')
    groups=[]
    for row in (normal,high):
        if not row['observer_vendor_unchanged'] or not row['owned_probe_directory_removed'] or row['leftover_workers']:raise ValueError('Unrestored observer test')
        events=row['probe']['ion_observations']
        if sorted(int(key) for key in events)!=list(range(len(events))):raise ValueError('Incomplete observer sequence')
        counts=collections.Counter()
        for event in events.values():
            if event['heapmask']!=1 or event['mapping_flags']!=512 or event['result']!=0:raise ValueError('Allocation parameters differ')
            counts[event['bytes']]+=1
        groups.append(dict(counts))
    samples=synthetic['probe']['samples']
    if [item['flags'] for item in samples]!=[0,1,0] or any(not item['all_pixels_match'] or item['samples']!=16 for item in samples):raise ValueError('Synthetic comparison differs')
    for suffix in ('stdout','stderr'):
        path=ROOT/'logs'/names[0]/('probe.'+suffix+'.raw')
        files[names[0]+'/'+path.name]=path.read_bytes()
    summary={'scope':'synthetic_cache_comparison_and_read_only_vendor_arguments',
             'real_video_cache_changed':False,'new_full_rate_playback_passes':0,
             'allocation_groups_by_bytes':groups,
             'synthetic':[dict(flags=x['flags'],copy_ms=x['copy_ns']/x['samples']/1e6,
                               sync_ms=x['sync_ns']/x['samples']/1e6) for x in samples],
             'files':{name:dict(bytes=len(body),sha256=hashlib.sha256(body).hexdigest()) for name,body in files.items()}}
    files['SUMMARY.json']=json.dumps(summary,indent=2).encode('utf-8')
    files['README.txt']=('This is not a new video playback performance pass.\n'
        'The CPU-only synthetic buffers used flags 0, 1, 0 and matched every output byte.\n'
        'Real video allocation arguments were observed without modifying them.\n'
        'Vendor binary copies, credentials, URLs and original system logs are not included.\n'
        'Existing raw ADB stdout/stderr and exit statuses remain in the original local run directories.\n').encode('ascii')
    output=ROOT/'logs'/('BiliP011-IONCache-Audit-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.zip')
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as archive:
        for name,body in files.items():archive.writestr(name,body)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None or any(archive.read(name)!=body for name,body in files.items()):raise ValueError('Archive differs')
    print(json.dumps(summary,indent=2));print('RESULT_ZIP='+str(output));print('SHA256='+hashlib.sha256(output.read_bytes()).hexdigest())

if __name__=='__main__':main()
