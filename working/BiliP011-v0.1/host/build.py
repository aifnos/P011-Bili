"""Run a PC-only build command with separate logs and an explicit status."""
import datetime
import json
import pathlib
import subprocess
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
ROOT = BASE.parents[1]


def main():
    out = ROOT / "logs" / ("BiliP011-Build-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    out.mkdir(parents=True, exist_ok=False)
    command = sys.argv[1:]
    if not command:
        raise SystemExit("Usage: build.py command arguments...")
    print("LOG_DIR=" + str(out), flush=True)
    with (out / "stdout.raw").open("wb") as stdout, (out / "stderr.raw").open("wb") as stderr:
        child = subprocess.Popen(command, cwd=BASE, stdout=stdout, stderr=stderr)
        code = child.wait()
    (out / "result.json").write_text(json.dumps({"command": command, "host_exit": code, "device_tested": False}, indent=2), encoding="utf-8")
    print("HOST_EXIT=" + str(code), flush=True)
    if code:
        print((out / "stderr.raw").read_text(encoding="utf-8", errors="replace")[-5000:])
    raise SystemExit(code)


if __name__ == "__main__":
    main()
