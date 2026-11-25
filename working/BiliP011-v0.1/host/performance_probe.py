"""Read-only capability inventory; no decoder, window, radio or login started."""
import datetime
import json
from probe_device import ROOT, NATIVE, Adb, result_from, archive


def main():
    out = ROOT / 'logs' / ('BiliP011-PerformanceProbe-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir()
    adb = Adb(out)
    safety = (NATIVE / 'runtime/native_safety.py').read_text(encoding='utf-8')
    snapshot = safety + "\ns=stock_snapshot();require_stock(s);print('RESULT='+repr(s))"
    before = result_from(adb.python('before', snapshot))
    capabilities = result_from(adb.python('capabilities', r'''
import os,glob,subprocess
cpu=[]
for line in open('/proc/cpuinfo'):
 if line.split(':',1)[0].strip() in ('processor','model name','CPU architecture','CPU part','Features'):cpu.append(line.strip())
mem={}
for line in open('/proc/meminfo'):
 k,v=line.split(':',1)
 if k in ('MemTotal','MemAvailable','SwapTotal'):mem[k]=v.strip()
patterns=['/dev/*vpu*','/dev/*video*','/dev/*v4l*','/dev/*vsp*','/usr/lib/*omx*','/usr/lib/*OMX*','/usr/lib/*stagefright*','/usr/lib/gstreamer-1.0/*omx*','/usr/lib/gstreamer-1.0/*v4l*','/usr/lib/qt5/plugins/platforminputcontexts/*','/usr/lib/qt5/qml/QtQuick/VirtualKeyboard/*','/usr/share/qtvirtualkeyboard/*','/usr/lib/qt5/qml/QtQuick/VirtualKeyboard/Layouts/*']
qt=[]
for proc in glob.glob('/proc/[0-9]*'):
 try:
  if os.readlink(proc+'/exe')!='/usr/bin/Z03':continue
  qt=[s.decode('ascii','replace') for s in open(proc+'/environ','rb').read().split(b'\0') if s.startswith((b'QT_IM_MODULE=',b'QT_VIRTUALKEYBOARD_',b'QML2_IMPORT_PATH='))]
 except OSError:pass
print('RESULT='+repr({'cpu':cpu,'memory':mem,'qt_input_environment':qt,'paths':{p:glob.glob(p) for p in patterns}}))
'''))
    results = {}
    for name, command in (('omx', ['gst-inspect-1.0', 'omx']), ('v4l2', ['gst-inspect-1.0', 'video4linux2']), ('omx-config', ['sh', '-c', "for p in /etc/xdg/gstomx.conf /etc/gstomx.conf; do if test -f $p; then head -n 240 $p; fi; done"])):
        code = "import subprocess\np=subprocess.Popen(" + repr(command) + ",stdout=subprocess.PIPE,stderr=subprocess.PIPE)\ntry:\n o,e=p.communicate(timeout=12)\nexcept subprocess.TimeoutExpired:\n p.kill();o,e=p.communicate()\nprint('RESULT='+repr({'exit':p.returncode,'stdout':o[:65536],'stderr':e[:4096]}))"
        result = result_from(adb.python(name, code, timeout=20))
        (out / (name + '.txt')).write_bytes(result['stdout'] + result['stderr'])
        results[name] = {'exit':result['exit'],'stdout_bytes':len(result['stdout'])}
    after = result_from(adb.python('after', snapshot))
    report = {'device_writes':False,'capabilities':capabilities,'probes':results,
              'stock_hashes_unchanged':before['hashes']==after['hashes'],
              'stock_processes_unchanged':before['processes']==after['processes']}
    (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('LOG_DIR=' + str(out))
    archive(out)


if __name__ == '__main__':
    main()
