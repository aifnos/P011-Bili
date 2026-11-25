"""Read-only P011 ABI/media/HTTPS probe. Never starts a UI or logs in."""
import datetime
import json
import pathlib
import shlex
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
ROOT = BASE.parents[1]
NATIVE = ROOT / "working" / "ToolboxNext-v0.5.1-native"
sys.path.insert(0, str(NATIVE / "host"))
from native_trial import Adb, archive, result_from


def main():
    out = ROOT / "logs" / ("BiliP011-Probe-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    out.mkdir(parents=True, exist_ok=False)
    adb = Adb(out)
    safety = (NATIVE / "runtime" / "native_safety.py").read_text(encoding="utf-8")
    snapshot_code = safety + "\ns=stock_snapshot();require_stock(s);print('RESULT='+repr(s))"
    before = result_from(adb.python("before", snapshot_code))
    metadata = result_from(adb.python("capabilities", r'''
import os,sys,glob,ctypes,time
libc=ctypes.CDLL('libc.so.6');libc.gnu_get_libc_version.restype=ctypes.c_char_p
patterns=['/usr/bin/curl','/usr/bin/ffmpeg','/usr/bin/gst-*','/usr/include/SDL*','/usr/include/EGL/*','/usr/include/GLES2/*','/usr/include/pulse/*','/usr/lib/libav*.so*','/usr/lib/libsw*.so*','/usr/lib/libcurl*','/usr/lib/libssl*','/usr/lib/libcrypto*','/usr/lib/libpulse*.so*','/usr/lib/libwayland*.so*','/usr/lib/libSDL2*','/usr/lib/libEGL*','/usr/lib/libGLESv2*','/lib/ld-linux*','/etc/ssl/certs/ca-certificates.crt']
mods={}
for name in ['ssl','http.client','urllib.request']:
 try:__import__(name);mods[name]=True
 except ImportError:mods[name]=False
print('RESULT='+repr({'machine':os.uname()[4],'pointer_bits':ctypes.sizeof(ctypes.c_void_p)*8,'glibc':libc.gnu_get_libc_version().decode(),'unix_time':int(time.time()),'python':sys.version.split()[0],'paths':{p:glob.glob(p) for p in patterns},'modules':mods}))
'''))
    report = {"device_writes": False, "account_used": False, "capabilities": metadata, "checks": {}}
    commands = {
        "curl-version": "curl --version",
        "ffmpeg-version": "ffmpeg -version",
        "gstreamer-version": "gst-inspect-1.0 --version",
        "gstreamer-omx": "gst-inspect-1.0 omx",
        "gstreamer-sinks": "gst-inspect-1.0 waylandsink",
        "gstreamer-h264": "gst-inspect-1.0 avdec_h264",
        "anonymous-nav": "curl --silent --show-error --connect-timeout 5 --max-time 12 --max-filesize 1048576 --proto '=https' -A wiliwili -e https://www.bilibili.com/client https://api.bilibili.com/x/web-interface/nav",
        "public-video": "curl --silent --show-error --connect-timeout 5 --max-time 12 --max-filesize 1048576 --proto '=https' -A wiliwili -e https://www.bilibili.com/client 'https://api.bilibili.com/x/web-interface/view?bvid=BV1Da411Y7U4'",
    }
    try:
        for name, command in commands.items():
            bounded = "import subprocess\np=subprocess.Popen(" + repr(["sh", "-c", command]) + ",stdout=subprocess.PIPE,stderr=subprocess.PIPE)\ntry:\n o,e=p.communicate(timeout=15)\nexcept subprocess.TimeoutExpired:\n p.kill();o,e=p.communicate();e+=b'\\nPROBE_TIMEOUT'\nprint('RESULT='+repr({'exit':p.returncode,'stdout':o,'stderr':e}))"
            answer = result_from(adb.python(name, bounded, timeout=22))
            report["checks"][name] = {"command_exit": answer["exit"], "stdout_bytes": len(answer["stdout"]), "stderr_bytes": len(answer["stderr"])}
            if name in ("anonymous-nav", "public-video"):
                try:
                    value = json.loads(answer["stdout"])
                    report["checks"][name]["api_code"] = value.get("code")
                    data = value.get("data") or {}
                    if name == "anonymous-nav":
                        report["checks"][name]["is_login"] = data.get("isLogin", False)
                        report["checks"][name]["has_wbi_keys"] = bool(data.get("wbi_img"))
                    else:
                        report["checks"][name]["pages"] = len(data.get("pages", []))
                except (ValueError, TypeError):
                    report["checks"][name]["api_json"] = False
            else:
                (out / (name + ".txt")).write_bytes(answer["stdout"] + answer["stderr"])
    finally:
        after = result_from(adb.python("after", snapshot_code))
        report["stock_hashes_unchanged"] = before["hashes"] == after["hashes"]
        report["stock_processes_unchanged"] = before["processes"] == after["processes"]
        (out / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print("LOG_DIR=" + str(out))
        archive(out)


if __name__ == "__main__":
    main()
