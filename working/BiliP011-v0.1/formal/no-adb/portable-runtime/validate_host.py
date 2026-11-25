"""First compatibility check for the changed private runtime; never runs core."""
import argparse
import ctypes
import hashlib
import importlib.util
import io
import json
import pathlib
import ssl
import sys
import zipfile
import zlib


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    runtime = pathlib.Path(sys.executable).resolve().parent
    app = pathlib.Path(__file__).resolve().parent.parent
    assert sys.version_info[:3] == (3, 14, 8) and ctypes.sizeof(ctypes.c_void_p) == 8
    assert sys.flags.isolated == 1 and sys.flags.ignore_environment == 1 and sys.flags.no_site == 1
    expected = [runtime / "python314.zip", runtime, app]
    assert [pathlib.Path(p).resolve() for p in sys.path] == expected
    assert importlib.util.find_spec("p011_environment_path_must_not_load") is None
    assert "site" not in sys.modules
    raw = "P011 HOST 隔离运行时\0".encode("utf-8")
    assert zlib.decompress(zlib.compress(raw)) == raw
    assert json.loads(json.dumps({"test": raw.decode("utf-8")}))["test"] == raw.decode("utf-8")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # No socket/connection/cert-store operation.
    assert context.verify_mode == ssl.CERT_REQUIRED
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("host.bin", raw)
    with zipfile.ZipFile(io.BytesIO(stream.getvalue())) as bundle:
        assert bundle.testzip() is None and bundle.read("host.bin") == raw
    code_names = ("early_mode_probe.py", "bsl_frames.py", "win32_download_transport.py",
                  "run_early_mode_probe.py", "continue_autod_handshake.py", "run_continue_autod.py")
    before = {name: hashlib.sha256((app / name).read_bytes()).hexdigest() for name in code_names}
    for name in code_names:
        compile((app / name).read_bytes(), str(app / name), "exec")  # Compile only; no core execution/import.
    import win32_download_transport as transport
    assert transport._API is None
    abi = transport.self_check()  # Pure structure sizes only; no DLL/API or inventory.
    assert transport._API is None
    import run_early_mode_probe as wrapper
    constructed = wrapper._child_command(app, out / "never-created-real-core-output", 1)
    assert pathlib.Path(constructed[0]).resolve() == pathlib.Path(sys.executable).resolve()
    assert constructed[1] == "-u" and pathlib.Path(constructed[2]).resolve() == app / "early_mode_probe.py"
    fake = [sys.executable, "-u", "-c", "import sys;sys.stdout.buffer.write(b'HOST-ARMED\\r\\n\\x00\\xff');sys.stdout.flush();sys.stderr.buffer.write(b'HOST-ERR\\r\\r\\n');sys.stderr.flush()"]
    capture = out / "fake-child-contract"
    capture.mkdir()
    with wrapper.ExclusiveLock(out / "host-only-runtime.lock"):
        status = wrapper._capture(fake, capture, 10, stdout_target=io.BytesIO())
    assert status["host_exit"] == 0 and status["streams_complete"] and not status["timeout"]
    assert not status["capture_errors"] and not status["stdout_forward_errors"]
    assert (capture / "host.stdout.raw").read_bytes() == b"HOST-ARMED\r\n\x00\xff"
    assert (capture / "host.stderr.raw").read_bytes() == b"HOST-ERR\r\r\n"
    archive, digest = wrapper._archive(capture)
    after = {name: hashlib.sha256((app / name).read_bytes()).hexdigest() for name in code_names}
    assert before == after
    assert "early_mode_probe" not in sys.modules and "continue_autod_handshake" not in sys.modules
    report = {"scope": "HOST_ONLY_NEW_RUNTIME_COMPATIBILITY", "version": sys.version,
              "executable": sys.executable, "isolated_sys_path": sys.path, "abi": abi,
              "zlib_version": zlib.ZLIB_RUNTIME_VERSION, "ssl_version": ssl.OPENSSL_VERSION,
              "fake_child_status": status, "fake_child_zip": str(archive), "fake_child_zip_sha256": digest,
              "project_source_sha256": before, "project_sources_unchanged": True,
              "inventory_called": False, "serial_opened": False, "real_core_called": False,
              "driver_status": "NOT_READY_REDISTRIBUTION_LICENSE_UNVERIFIED"}
    (out / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
