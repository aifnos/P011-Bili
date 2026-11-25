"""Portable Windows entry: record failures before installer initialization."""
import datetime
import os
from pathlib import Path
import shutil
import sys
import traceback

HERE=Path(__file__).resolve().parent


class Tee:
    def __init__(self,stream,log):self.stream,self.log=stream,log
    def write(self,value):
        self.log.write(value);self.log.flush()
        self.stream.write(value);self.stream.flush()
        return len(value)
    def flush(self):self.log.flush();self.stream.flush()
    def __getattr__(self,name):return getattr(self.stream,name)


def main():
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='replace')
    early=os.environ.get('P011_STARTUP_LOG')
    if early:
        logpath=Path(early)
        if logpath.parent.resolve()!=HERE/'startup-logs':
            raise RuntimeError('Unexpected startup log directory')
    else:
        logpath=HERE/'startup-logs'/('startup-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.txt')
        logpath.parent.mkdir(exist_ok=True)
    with logpath.open('a',encoding='utf8') as log:
        previous=(sys.stdout,sys.stderr)
        sys.stdout=Tee(previous[0],log);sys.stderr=Tee(previous[1],log)
        rc=1
        try:
            print('STARTUP_LOG='+str(logpath),flush=True)
            print('运行时：'+sys.version.split()[0]+' / '+sys.executable,flush=True)
            adb=shutil.which('adb')
            print('ADB：'+(adb or '未找到；请把现有 adb.exe 放在 PATH 中，或重新打开能运行 adb 的终端。'),flush=True)
            if not (HERE/'install_formal.py').is_file():
                raise RuntimeError('安装包未完整解压：缺少 install_formal.py')
            import install_formal
            sys.argv=[str(HERE/'install_formal.py')]+sys.argv[1:]
            rc=install_formal.main()
        except BaseException as exc:
            if isinstance(exc,SystemExit):rc=exc.code if isinstance(exc.code,int) else 1
            else:
                print('启动失败：'+type(exc).__name__+': '+str(exc),flush=True)
                traceback.print_exc()
        finally:
            print('EXIT_CODE='+str(rc),flush=True)
            sys.stdout,sys.stderr=previous
        return rc


if __name__=='__main__':raise SystemExit(main())
