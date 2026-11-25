"""Offline, fixed-backup kernel capability audit. No ADB, mount or device I/O."""
import datetime
import hashlib
import json
import re
import zipfile
import zlib

from inspect_kernel_graphics import BOOT,ROOT,inspect

KERNEL_SHA256='c87903edc38cbce8053a600c83590777cf1b821e1a7bafbced090d681116fb30'
KEYS=('CONFIG_IKCONFIG','CONFIG_IKCONFIG_PROC','CONFIG_KALLSYMS','CONFIG_COMMON_CLK',
      'CONFIG_DEBUG_FS','CONFIG_SCHED_INFO','CONFIG_SCHEDSTATS','CONFIG_FTRACE','CONFIG_SPRD_VSP')


def decode_config(kernel):
    if type(kernel) is not bytes or len(kernel)>32*1024*1024:raise ValueError('Invalid kernel size')
    if kernel.count(b'IKCFG_ST')!=1 or kernel.count(b'IKCFG_ED')!=1:raise ValueError('Ambiguous config markers')
    start=kernel.index(b'IKCFG_ST')+8;end=kernel.index(b'IKCFG_ED')
    if end<=start:raise ValueError('Invalid config order')
    decoder=zlib.decompressobj(31)
    raw=decoder.decompress(kernel[start:end],512*1024+1)
    if not decoder.eof or decoder.unused_data or len(raw)>512*1024:raise ValueError('Invalid bounded config stream')
    result={key:'not_recorded' for key in KEYS};seen=set()
    for line in raw.decode('ascii').splitlines():
        match=re.fullmatch(r'(CONFIG_[A-Z0-9_]+)=([ymn])|# (CONFIG_[A-Z0-9_]+) is not set',line)
        if not match:continue
        key=match.group(1) or match.group(3)
        if key not in result:continue
        if key in seen:raise ValueError('Duplicate selected config')
        seen.add(key);result[key]=match.group(2) or 'n'
    return dict(config_sha256=hashlib.sha256(raw).hexdigest(),config_bytes=len(raw),selected_config=result,
                debug_clock_summary_unavailable=result['CONFIG_DEBUG_FS']=='n',
                ftrace_unavailable=result['CONFIG_FTRACE']=='n',
                scheduler_stats_unavailable=result['CONFIG_SCHEDSTATS']=='n')


def main():
    blob=BOOT.read_bytes();kernel,identity=inspect(blob)
    if identity['kernel_sha256']!=KERNEL_SHA256:raise ValueError('Different stock kernel; re-audit first')
    report=decode_config(kernel)
    report.update(schema=1,boot_sha256=hashlib.sha256(blob).hexdigest(),kernel_sha256=KERNEL_SHA256,
                  device_accessed=False,config_changed=False,actual_clock_measured=False,
                  irq_wakeup_latency_measured=False,performance_improvement_proven=False)
    out=ROOT/'logs'/('BiliP011-KernelObservability-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir()
    bodies={'result.json':json.dumps(report,indent=2).encode('ascii')}
    for name,body in bodies.items():(out/name).write_bytes(body)
    archive=out.with_name(out.name+'-safe.zip')
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for name,body in bodies.items():z.writestr(name,body)
        z.writestr('SHA256.json',json.dumps({name:hashlib.sha256(body).hexdigest() for name,body in bodies.items()},indent=2))
    with zipfile.ZipFile(archive) as z:
        if z.testzip() or any(hashlib.sha256(z.read(name)).hexdigest()!=value for name,value in json.loads(z.read('SHA256.json')).items()):
            raise ValueError('Offline audit archive integrity failed')
    print(json.dumps(report,indent=2));print('RESULT_ZIP='+str(archive))
    print('ZIP_SHA256='+hashlib.sha256(archive.read_bytes()).hexdigest())


if __name__=='__main__':main()
