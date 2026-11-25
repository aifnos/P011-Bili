"""Reuse the verified local Python runtime; no downloads or device actions."""
import hashlib
import json
from pathlib import Path
import shutil

HERE=Path(__file__).resolve().parent
FORMAL=HERE.parent
PACKAGE=FORMAL/'out/P011-Bili-ADB-v8-reinstall-cache-20261014'
RUNTIME=FORMAL/'no-adb/portable-runtime/python-3.14.8-embed-amd64'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    destination=PACKAGE/'runtime'
    assert not destination.exists()
    original=json.loads((FORMAL/'no-adb/portable-runtime/manifest.json').read_bytes())
    upstream={row['name']:row for row in original['upstream_members']}
    for p in RUNTIME.iterdir():
        if p.is_file() and p.name in upstream and p.name!='python314._pth':
            assert sha(p)==upstream[p.name]['sha256'],p.name
    shutil.copytree(RUNTIME,destination)
    (destination/'python314._pth').write_text('python314.zip\n.\n..\n',encoding='ascii')
    shutil.copyfile(HERE/'adb_launcher.py',PACKAGE/'launcher.py')
    (PACKAGE/'source/playback-fix-v1/adb_launcher.py').write_bytes((HERE/'adb_launcher.py').read_bytes())
    shutil.copyfile(Path(__file__),PACKAGE/'source/playback-fix-v1/add_adb_portable_runtime.py')
    notices=FORMAL/'no-adb/portable-runtime/THIRD_PARTY_NOTICES.md'
    shutil.copyfile(notices,PACKAGE/'runtime/THIRD_PARTY_NOTICES.md')
    for name,action in (('一键正式写入B站.cmd','install'),('一键恢复用户反馈.cmd','restore'),
                        ('仅检查不写入.cmd','inspect'),('校验安装包.cmd','verify'),
                        ('检查已安装状态.cmd','status'),('一键修复反馈页缓存.cmd','repair-cache'),
                        ('检查电脑运行环境.cmd','verify')):
        cmd='''@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist "%~dp0startup-logs" mkdir "%~dp0startup-logs"
set "P011_STARTUP_LOG=%~dp0startup-logs\startup-%RANDOM%-%RANDOM%.txt"
echo P011 B站 ADB 启动记录 > "%P011_STARTUP_LOG%"
echo 启动日志：%P011_STARTUP_LOG%
if not exist "%~dp0runtime\python.exe" (
  echo 启动失败：缺少包内 Python，请完整解压整个文件夹。
  echo Missing bundled runtime\python.exe >> "%P011_STARTUP_LOG%"
  pause
  exit /b 2
)
"%~dp0runtime\python.exe" -B "%~dp0launcher.py" ACTION 2>> "%P011_STARTUP_LOG%"
set "P011_EXIT=%ERRORLEVEL%"
if not "%P011_EXIT%"=="0" (
  echo 操作未通过。启动日志内容如下：
  type "%P011_STARTUP_LOG%"
)
pause
exit /b %P011_EXIT%
'''.replace('ACTION',action)
        (PACKAGE/name).write_bytes(cmd.replace('\n','\r\n').encode('utf8'))
    readme=PACKAGE/'README.md'
    body=readme.read_text(encoding='utf8')
    body='''本版自带 Windows x64 Python，不需要在其他电脑另外安装 Python。
仍需该电脑能使用 adb.exe，设备需要已开启 root ADB。先完整解压整个目录，退出 B站后运行“一键正式写入B站.cmd”。
若启动失败，入口在 Python 启动前创建 startup-logs 日志；“检查电脑运行环境.cmd”只检查电脑与包，不写入设备。

'''+body
    body=body.replace('电脑需要 Python 3 和 adb。','电脑使用包内 Python，需现有 adb。')
    readme.write_text(body,encoding='utf8')
    report=dict(version=original['version'],upstream_zip_sha256=original['zip_sha256'],
                source=str(RUNTIME),python_sha256=sha(destination/'python.exe'),
                pth='python314.zip; .; ..',network_access=False)
    target=PACKAGE/'evidence/reinstall/runtime-provenance.json';target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,indent=2),encoding='utf8')
    listed=PACKAGE/'PACKAGE.sha256'
    listed.write_text(''.join(sha(p)+' '+str(p.stat().st_size)+' '+p.relative_to(PACKAGE).as_posix()+'\n'
        for p in sorted(PACKAGE.rglob('*')) if p.is_file() and p!=listed),encoding='utf8')
    print(json.dumps(report))


if __name__=='__main__':main()
