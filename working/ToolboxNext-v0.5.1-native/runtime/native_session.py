"""Finite independent Wayland toolbox; never stops/replaces the vendor UI."""
import argparse
import io
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback
import p011_json as J
from native_safety import AREA,identity,owned_directory,stock_snapshot,require_stock,verify_candidate
from server import State,BoundedServer


def write_new(path,payload):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as handle:
        handle.write(payload);handle.flush();os.fsync(handle.fileno())


def preview_fixture_png():
    # Generated diagnostic pixels, not a bundled vendor graphic/font/user photo.
    import struct,zlib
    def chunk(name,data):
        return struct.pack('!I',len(data))+name+data+struct.pack('!I',zlib.crc32(name+data)&0xffffffff)
    row=b'\x00'+b'\x12\xcf\xa7'*48+b'\x00\xb9\xf5'*48+b'\xff\x72\x56'*48
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',144,64,8,2,0,0,0))+
            chunk(b'IDAT',zlib.compress(row*64))+chunk(b'IEND',b''))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session',required=True)
    parser.add_argument('--seconds',type=int,default=600)
    parser.add_argument('--automated',action='store_true')
    args=parser.parse_args()
    if not 15<=args.seconds<=600:raise ValueError('Trial must be 15 to 600 seconds')
    base=os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    source=verify_candidate(base)
    if not re.match(r'^'+AREA+r'/sessions/[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$',args.session):
        raise ValueError('Unexpected session path')
    owned_directory(args.session)
    before=stock_snapshot();require_stock(before)
    lock=AREA+'/native.lock'
    os.mkdir(lock,0o700)  # Never clear an existing session/stale lock automatically.
    state=None;http=None;worker=None;child=None;stopping=threading.Event()
    result={'candidate':'v0.5.1-native','source_identity':source,'automated':args.automated,
            'before':before,'ui_exit':None,'duration_limit_seconds':args.seconds,
            'started_epoch':time.time(),'original_processes_signalled':False}
    def stop(signum,frame):stopping.set()
    for name in ('SIGTERM','SIGINT','SIGALRM'):signal.signal(getattr(signal,name),stop)
    signal.alarm(args.seconds+35)
    try:
        write_new(lock+'/session.txt',args.session+'\n')
        write_new(args.session+'/owner.json',J.dumps(identity(os.getpid()),indent=2))
        write_new(args.session+'/before.json',J.dumps(before,indent=2))
        userroot=args.session+'/test-user' if args.automated else AREA+'/user'
        state=State(owned_directory(userroot,True),False)
        if args.automated:
            text='P011 原生工具箱\n中文 TXT 真机预览测试。\n这是合成测试内容，不是用户文件。'.encode('utf-8')
            state.store.write_new('Text/native-ui-test.txt',io.BytesIO(text),len(text))
            pixels=preview_fixture_png()
            state.store.write_new('Pictures/native-ui-test.png',io.BytesIO(pixels),len(pixels))
        http=BoundedServer(('127.0.0.1',0),state)
        worker=threading.Thread(target=http.serve_forever);worker.daemon=True;worker.start()
        state.arm_native_bootstrap(30)
        with open(base+'/runtime/NativeTrial.qml',encoding='utf-8') as handle:template=handle.read()
        values={'DEVICE_URL':'file://'+base+'/device','AUTOMATED':'true' if args.automated else 'false',
                'SECONDS':str(args.seconds),'CAPTURE_DIR':args.session,'ENDPOINT':'http://'+http.expected_host}
        for key,value in values.items():template=template.replace('@@'+key+'@@',value)
        if '@@' in template:raise ValueError('Unresolved QML template')
        qml=args.session+'/tst_native.qml';write_new(qml,template)
        env=dict(os.environ)
        env.update({'XDG_RUNTIME_DIR':'/run/user/0','WAYLAND_DISPLAY':'wayland-0',
                    'QT_QPA_PLATFORM':'wayland','QT_QUICK_BACKEND':'software','QSG_RENDER_LOOP':'basic',
                    'QML_DISABLE_DISK_CACHE':'1','PYTHONDONTWRITEBYTECODE':'1'})
        with open(args.session+'/ui.stdout.raw','xb') as stdout,open(args.session+'/ui.stderr.raw','xb') as stderr:
            child=subprocess.Popen([sys.executable,'-B',base+'/runtime/qt_quicktest_runner.py','--input',qml],
                                   stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,env=env)
            result['ui_identity']=identity(child.pid)
            write_new(args.session+'/started.json',J.dumps({'owner':identity(os.getpid()),'ui':result['ui_identity'],
                        'seconds':args.seconds,'automated':args.automated,'loopback_port':http.server_address[1]},indent=2))
            deadline=time.monotonic()+args.seconds+15
            while child.poll() is None and time.monotonic()<deadline and not stopping.wait(.2):
                if os.path.isfile(args.session+'/STOP'):result['stop_requested']=True;break
            if child.poll() is None:
                result['supervisor_terminated_own_ui']=True
                child.terminate()
                try:child.wait(5)
                except subprocess.TimeoutExpired:child.kill();child.wait(3)
            result['ui_exit']=child.returncode
    except Exception as exc:
        result['error']=type(exc).__name__+': '+str(exc)
        traceback.print_exc()
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:child.wait(3)
            except subprocess.TimeoutExpired:child.kill();child.wait(3)
        if http:
            address=http.server_address
            http.shutdown();http.server_close()
            # On Linux a socket closed from another thread can stay alive until
            # the bounded accept() returns. Join our accept loop before probing.
            if worker:worker.join(2)
            result['serve_closed']=worker is None or not worker.is_alive()
            probe=socket.socket(socket.AF_INET,socket.SOCK_STREAM);probe.settimeout(.5)
            try:result['loopback_closed']=probe.connect_ex(address)!=0
            finally:probe.close()
        if state:
            state.close()
            result['page_events']=[r for r in state.events if r['event'].startswith('page_')]
            result['transfer_closed']=state.lan is None
            result['audio_closed']=state.audio.audio is None
            result['sampler_closed']=not state.worker.is_alive()
        result['own_ui_closed']=child is None or child.poll() is not None
        result['after']=stock_snapshot()
        result['stock_hashes_unchanged']=result['after']['hashes']==before['hashes']
        result['stock_processes_unchanged']=result['after']['processes']==before['processes']
        result['finished_epoch']=time.time()
        result['passed']=all(result.get(k,False) for k in ('stock_hashes_unchanged','stock_processes_unchanged',
                            'own_ui_closed','loopback_closed','serve_closed','sampler_closed','transfer_closed','audio_closed')) and result['ui_exit']==0 and 'error' not in result
        write_new(args.session+'/result.json',J.dumps(result,indent=2))
        if os.path.isfile(lock+'/session.txt'):
            with open(lock+'/session.txt') as handle:ours=handle.read()==args.session+'\n'
            if ours:os.unlink(lock+'/session.txt');os.rmdir(lock)
        signal.alarm(0)
    return 0 if result['passed'] else 1


if __name__=='__main__':sys.exit(main())
