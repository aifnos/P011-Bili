"""Audio-only extraction of fourth-round gst-play position backend.
Original radio/ADB/SSH bridge is not imported or started. Physical v2.4.0
audio output remains a device acceptance item.
"""
import os, re, time, threading, subprocess, select
def path_url(p):
    safe=b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~/'
    raw=p.encode('utf-8') if os.name=='posix' else os.fsencode(p)
    return 'file://'+''.join(chr(x) if x in safe else '%%%02X'%x for x in raw)

def parse_gst_play_frame(frame):
    """Parse one gst-play query frame, without inventing an elapsed clock."""
    if isinstance(frame,bytes):frame=frame.decode('utf-8','replace')
    frame=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',frame)
    match=re.search(r'(?<!\d)(\d+):(\d{2}):(\d{2})(?:\.(\d+))?\s*/\s*(\d+):(\d{2}):(\d{2})(?:\.(\d+))?',frame)
    if not match:return None
    values=match.groups();result=[]
    for offset in (0,4):
        hours,minutes,seconds=[int(x) for x in values[offset:offset+3]]
        if minutes>59 or seconds>59:return None
        fraction=int(((values[offset+3] or '')+'000')[:3])
        result.append(((hours*60+minutes)*60+seconds)*1000+fraction)
    return {'position_ms':result[0],'duration_ms':result[1]}


class AudioEngine:
    def __init__(self, logs, event, launcher=None):
        self.logs=logs; self.event=event; self.lock=threading.RLock()
        self.launcher=launcher
        self.audio=None; self.audio_reader=None; self.audio_reader_stop=None
        self.audio_generation=int(time.time()*1000)
        self.audio_state=self.new_audio_state(self.audio_generation,'stopped')
    def play(self,path,volume=25):
        if not 0<=volume<=100: raise ValueError('音量无效')
        self.stop_audio()
        gst=next((p for p in ('/usr/bin/gst-play-1.0','/bin/gst-play-1.0') if os.path.isfile(p)),None)
        if not gst: raise RuntimeError('此环境无 gst-play 音频后端')
        self.audio_generation+=1
        generation=self.audio_generation
        self.audio_state=self.new_audio_state(generation,'starting')
        stdout_log=stderr_log=None
        env=dict(os.environ); env['LC_ALL']='C'
        try:
            stdout_log=open(self.logs+'/audio-%d.stdout.raw'%generation,'xb',buffering=0)
            stderr_log=open(self.logs+'/audio-%d.stderr.raw'%generation,'xb',buffering=0)
            command=[gst,'--no-interactive','--audiosink=pulsesink',
                '--volume=%.2f'%(volume/100.0),path_url(path)]
            if self.launcher: command,env=self.launcher(command,env)
            proc=subprocess.Popen(command,stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,close_fds=True,env=env)
        except Exception:
            for handle in (stdout_log,stderr_log):
                if handle is not None:handle.close()
            self.audio_state.update({'status':'error','error':'音频后端启动失败'})
            raise
        stop=threading.Event()
        reader=threading.Thread(target=self.read_audio,args=(proc,generation,stop,stdout_log,stderr_log))
        reader.daemon=True
        self.audio=proc; self.audio_reader=reader; self.audio_reader_stop=stop
        self.audio_state['process_alive']=True
        try:reader.start()
        except Exception:
            self.audio_reader=None
            self.stop_audio()
            for handle in (proc.stdout,proc.stderr,stdout_log,stderr_log):handle.close()
            raise
        return self.audio_snapshot()
    @staticmethod
    def new_audio_state(generation,status):
        return {'generation':generation,'status':status,'playing':False,'process_alive':False,'position_ms':0,'duration_ms':0,'position_sample_epoch_ms':0,'position_sample_monotonic_ms':0,'position_source':'gst_play_query','position_samples':0,'exit_code':None,'error':''}
    def audio_snapshot(self):
        with self.lock:
            proc=self.audio;reader=self.audio_reader
            draining=proc is not None and proc.poll() is not None and self.audio_state['status'] in ('starting','playing')
        if draining and reader is not None and reader is not threading.current_thread():reader.join(timeout=.5)
        with self.lock:
            state=dict(self.audio_state)
            state['process_alive']=self.audio is not None and self.audio.poll() is None
            if not state['process_alive'] and state['status'] in ('starting','playing'):
                state.update({'status':'error','error':'音频进程已退出，结束信息未完成读取','exit_code':self.audio.poll() if self.audio is not None else None})
            state['playing']=state['status']=='playing' and state['process_alive']
        return state
    def read_audio(self,proc,generation,stop_reader,stdout_log,stderr_log):
        streams={proc.stdout.fileno():(proc.stdout,stdout_log),proc.stderr.fileno():(proc.stderr,stderr_log)}
        buffers={fd:b'' for fd in streams};stdout_fd=proc.stdout.fileno();eos=False;backend_error=False;samples=0;reader_error=''
        def frame_received(fd,frame):
            nonlocal eos,backend_error,samples
            clean=re.sub(br'\x1b\[[0-?]*[ -/]*[@-~]',b'',frame).strip()
            if clean.startswith((b'ERROR ',b'ERROR:',b'Error ',b'Error:')):backend_error=True
            if fd!=stdout_fd:return
            if b'Reached end of play list.' in clean:eos=True
            sample=parse_gst_play_frame(clean)
            if sample is None:return
            epoch_ms=int(time.time()*1000);monotonic_ms=int(time.monotonic()*1000);samples+=1
            with self.lock:
                if self.audio is not proc or self.audio_generation!=generation or stop_reader.is_set():return
                self.audio_state.update(sample)
                self.audio_state.update({'status':'playing','playing':True,'process_alive':True,'position_sample_epoch_ms':epoch_ms,'position_sample_monotonic_ms':monotonic_ms,'position_samples':samples})
        try:
            while streams and not stop_reader.is_set():
                ready,_,_=select.select(list(streams),[],[],.2)
                for fd in ready:
                    block=os.read(fd,4096)
                    if not block:
                        if buffers[fd]:frame_received(fd,buffers[fd])
                        del streams[fd];del buffers[fd];continue
                    streams[fd][1].write(block)
                    frames=re.split(br'[\r\n]',buffers[fd]+block)
                    buffers[fd]=frames.pop()[-8192:]
                    for frame in frames:frame_received(fd,frame)
            if not stop_reader.is_set():
                try:code=proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    code=None;reader_error='音频后端关闭输出后未退出'
                if reader_error:error=reader_error
                elif backend_error:error='音频后端报告错误（见独立 stdout/stderr 日志）'
                elif code!=0:error='音频后端异常退出：'+str(code)
                elif not eos:error='音频后端退出但未报告正常播放结束'
                elif not samples:error='音频后端结束前没有有效播放位置'
                else:error=''
                with self.lock:
                    if self.audio is proc and self.audio_generation==generation:
                        self.audio_state.update({'status':'error' if error else 'ended','playing':False,'process_alive':proc.poll() is None,'exit_code':code,'error':error})
                self.event('media_backend_exit:generation=%d:code=%s:eos=%d:samples=%d:error=%s'%(generation,str(code),int(eos),samples,error))
        except Exception as e:
            reader_error='音频位置读取失败：'+type(e).__name__
            with self.lock:
                if self.audio is proc and self.audio_generation==generation and not stop_reader.is_set():
                    self.audio_state.update({'status':'error','playing':False,'error':reader_error})
            self.event('media_backend_reader_error:generation=%d:%s'%(generation,type(e).__name__))
        finally:
            for stream in (proc.stdout,proc.stderr,stdout_log,stderr_log):
                try:stream.close()
                except Exception:pass
    def stop_audio(self):
        with self.lock:
            proc=self.audio;reader=self.audio_reader;stop_reader=self.audio_reader_stop
            self.audio=None;self.audio_reader=None;self.audio_reader_stop=None
            self.audio_state=self.new_audio_state(self.audio_generation,'stopped')
        if stop_reader is not None:stop_reader.set()
        if proc is not None and proc.poll() is None:
            try:proc.terminate()
            except ProcessLookupError:pass
            try:proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:proc.kill()
                except ProcessLookupError:pass
                proc.wait(timeout=1)
        if reader is not None:
            reader.join(timeout=1)
            if reader.is_alive():raise RuntimeError('音频读取线程尚未停止')
