"""Collect only selected build headers/libraries, locally. No device mutation."""
import datetime
import hashlib
import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
ROOT = BASE.parents[1]
NATIVE = ROOT / "working" / "ToolboxNext-v0.5.1-native"
sys.path.insert(0, str(NATIVE / "host"))
from native_trial import Adb, result_from


def main():
    out = ROOT / "logs" / ("BiliP011-LinkSysroot-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    out.mkdir(parents=True, exist_ok=False)
    dest = BASE / "private-linksysroot"
    dest.mkdir(exist_ok=True)
    adb = Adb(out)
    safety = (NATIVE / "runtime" / "native_safety.py").read_text(encoding="utf-8")
    gate = safety + "\ns=stock_snapshot();require_stock(s);print('RESULT='+repr(s))"
    before = result_from(adb.python("before", gate))
    selected = result_from(adb.python("list", r'''
import os,glob,hashlib
paths=[]
for stem in ['SDL2-2.0','EGL','GLESv2','mali','pulse','pulse-simple','freetype','harfbuzz','fribidi','ass','z','png16','wayland-client','wayland-egl','wayland-cursor','xkbcommon','ffi','stdc++']:
 for path in sorted(glob.glob('/usr/lib/lib'+stem+'.so*')+glob.glob('/lib/lib'+stem+'.so*')):
  if not os.path.islink(path):paths.append(path)
headers=[]
for name in ['pulse','freetype2','harfbuzz','fribidi','ass','wayland-client.h','wayland-client-core.h','wayland-client-protocol.h','wayland-util.h','wayland-version.h','wayland-egl.h','wayland-cursor.h','EGL','GLES2','KHR','zlib.h','zconf.h']:
 p='/usr/include/'+name
 if os.path.exists(p):headers.append(p)
print('RESULT='+repr({'libraries':[{'path':p,'size':os.path.getsize(p),'sha256':hashlib.sha256(open(p,'rb').read()).hexdigest()} for p in paths],'headers':headers}))
'''))
    try:
        for row in selected["libraries"]:
            name = row["path"]
            path = dest / name.lstrip("/")
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                adb.run("pull-lib", ["pull", name, str(path)])
            if path.stat().st_size != row["size"] or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
                raise ValueError("Library pull verification failed")
        (dest / "usr" / "include").mkdir(parents=True, exist_ok=True)
        for name in selected["headers"]:
            if not (dest / name.lstrip("/")).exists():
                adb.run("pull-header", ["pull", name, str(dest / "usr" / "include")])
    finally:
        after = result_from(adb.python("after", gate))
        selected["stock_unchanged"] = before == after
        selected["device_writes"] = False
        selected["distribution"] = "PRIVATE_LINK_ONLY_DO_NOT_PACKAGE_VENDOR_LIBS"
        (dest / "manifest.json").write_text(json.dumps(selected, indent=2), encoding="utf-8")
        (out / "result.json").write_text(json.dumps(selected, indent=2), encoding="utf-8")
        print(json.dumps(selected, indent=2))
        print("LOG_DIR=" + str(out))


if __name__ == "__main__":
    main()
