"""Native toolbox shares the bounded service lifetime, not its account data."""
import io,os,struct,sys,threading,zlib
from toolbox_server import State,BoundedServer
USER_ROOT='/mnt/data/p011-toolbox/user'

def data_root(root,isolated):
    # Preserve the native toolbox's existing files and high scores. The server
    # CLI fallback /mnt/data/p011-user is not the accepted native-session path.
    return root+'/qa-user' if isolated else USER_ROOT

class Toolbox:
    def __init__(self,root,automated=False,preview=False):
        self.root=root
        def launcher(command,env):
            env=dict(env,P011_TOOLBOX_ROOT=root,P011_AUDIO_OWNER=str(os.getpid()))
            # No inherited private libmpv/FFmpeg path in the vendor gst process.
            env.pop('LD_LIBRARY_PATH',None);env.pop('LD_PRELOAD',None)
            return [sys.executable,'-B',root+'/audio_guard.py']+command,env
        user_root=data_root(root,automated or preview)
        if not preview:
            from native_safety import owned_directory
            user_root=owned_directory(user_root,True)
        self.state=State(user_root,preview,audio_launcher=launcher,flat_web_root=root)
        try:
            if automated:self.fixtures()
            self.server=BoundedServer(('127.0.0.1',0),self.state)
            self.state.arm_native_bootstrap(60)
            self.thread=threading.Thread(target=self.server.serve_forever);self.thread.daemon=True;self.thread.start()
        except Exception:self.state.close();raise
    @property
    def endpoint(self):return 'http://'+self.server.expected_host
    def fixtures(self):
        def write(name,data):self.state.store.write_new(name,io.BytesIO(data),len(data))
        write('Text/界面测试.txt','小屏幕，也能认真阅读。\n上下滑动查看完整文本。\n此文件仅用于自动验收，不读取个人文件。\n第四行：中文与 ABC 123。\n第五行：返回后仍在文件中心。'.encode('utf-8'))
        def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
        rows=b''.join(b'\0'+b''.join(bytes((20+180*(x>=80),190 if y<45 else 65,175)) for x in range(160)) for y in range(90))
        png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',160,90,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b'')
        write('Pictures/界面测试.png',png)
    def stop_audio(self):
        with self.state.audio_control_lock:self.state.audio.stop_audio()
    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join(2);self.state.close()
