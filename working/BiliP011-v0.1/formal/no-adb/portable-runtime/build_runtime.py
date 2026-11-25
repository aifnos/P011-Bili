"""HOST-only, fixed official Python runtime acquisition; no device imports."""
import datetime
import hashlib
import json
import os
import pathlib
import stat
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile

BASE = pathlib.Path(__file__).resolve().parent
VERSION = "3.14.8"
ZIP_NAME = "python-3.14.8-embed-amd64.zip"
ZIP_URL = "https://www.python.org/ftp/python/3.14.8/" + ZIP_NAME
EXPECTED_SHA256 = "a93abe456ab01bd96d7a085b3cdb6566b3063f4241360d114142fbdb07f0a310"
RUNTIME_NAME = "python-3.14.8-embed-amd64"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def fetch(url, path, limit=33554432):
    request = urllib.request.Request(url, headers={"User-Agent": "P011-HOST-runtime-preparation/1"})
    with urllib.request.urlopen(request, timeout=30) as reply:
        final_url = reply.geturl()
        parsed = urllib.parse.urlsplit(final_url)
        if parsed.scheme != "https" or parsed.hostname != "www.python.org":
            raise RuntimeError("Unexpected download origin")
        raw = reply.read(limit + 1)
        if len(raw) > limit:
            raise RuntimeError("Download exceeds size bound")
        record = {"url": url, "final_url": final_url, "bytes": len(raw),
                  "sha256": sha(raw), "http_status": reply.status,
                  "last_modified": reply.headers.get("Last-Modified"),
                  "etag": reply.headers.get("ETag")}
    with path.open("xb") as stream:
        stream.write(raw)
    return record


def extract_new(archive, output):
    output.mkdir(exist_ok=False)
    root = output.resolve(strict=True)
    records, seen = [], set()
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise RuntimeError("Upstream ZIP CRC check failed")
        infos = bundle.infolist()
        if len(infos) > 256 or sum(row.file_size for row in infos) > 134217728:
            raise RuntimeError("Upstream ZIP exceeds extraction bounds")
        for row in infos:
            name = row.filename
            path = pathlib.PurePosixPath(name)
            if (not name or "\\" in name or ":" in name or "\0" in name or
                    path.is_absolute() or ".." in path.parts or
                    name.casefold() in seen or stat.S_ISLNK(row.external_attr >> 16)):
                raise RuntimeError("Unsafe/duplicate upstream ZIP member")
            seen.add(name.casefold())
            target = (root / pathlib.Path(*path.parts)).resolve()
            if not target.is_relative_to(root):
                raise RuntimeError("Upstream ZIP member escaped runtime directory")
            if row.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            raw = bundle.read(row)
            with target.open("xb") as stream:
                stream.write(raw)
            records.append({"name": name, "bytes": len(raw), "sha256": sha(raw),
                            "zip_crc32": "%08x" % row.CRC})
    return records


def main():
    sources = BASE / "sources"
    runtime = BASE / RUNTIME_NAME
    if sources.exists() or runtime.exists() or (BASE / "manifest.json").exists():
        raise RuntimeError("Existing runtime build preserved; use a new versioned directory")
    sources.mkdir()
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    logs = BASE / "logs" / ("host-" + now.strftime("%Y%m%d-%H%M%S-%f"))
    logs.mkdir(parents=True, exist_ok=False)
    downloads = []
    for url, name in (
        (ZIP_URL + ".spdx.json", ZIP_NAME + ".spdx.json"),
        (ZIP_URL + ".sigstore", ZIP_NAME + ".sigstore"),
        ("https://www.python.org/downloads/release/python-3148/", "official-release-3.14.8.html"),
        ("https://www.python.org/downloads/", "official-active-releases.html"),
        (ZIP_URL, ZIP_NAME),
    ):
        print("HOST_DOWNLOAD=" + url, flush=True)
        downloads.append(dict(fetch(url, sources / name), file=name))
    write_json(sources / "download.records.json", downloads)
    archive = sources / ZIP_NAME
    sbom = json.loads((sources / (ZIP_NAME + ".spdx.json")).read_text(encoding="utf-8"))
    package = next(row for row in sbom["packages"] if row.get("name") == "CPython")
    sbom_sha = next(row["checksumValue"] for row in package["checksums"] if row["algorithm"] == "SHA256")
    if package["downloadLocation"] != ZIP_URL or sbom_sha != EXPECTED_SHA256 or sha(archive.read_bytes()) != EXPECTED_SHA256:
        raise RuntimeError("Official SBOM and downloaded ZIP SHA-256 disagree")
    original_members = extract_new(archive, runtime)
    # Retain the complete upstream config before writing the isolated app config.
    pth = runtime / "python314._pth"
    original_pth = runtime / "python314._pth.upstream"
    if not pth.resolve().is_relative_to(runtime.resolve()) or original_pth.exists():
        raise RuntimeError("Unexpected runtime configuration path")
    pth.rename(original_pth)
    with pth.open("x", encoding="ascii", newline="\n") as stream:
        stream.write("python314.zip\n.\n..\\..\n# P011 app path only; site/environment paths stay disabled.\n")
    runtime_members = [{"name": p.relative_to(runtime).as_posix(), "bytes": p.stat().st_size,
                        "sha256": sha(p.read_bytes())} for p in sorted(runtime.rglob("*")) if p.is_file()]
    write_json(BASE / "manifest.json", {"version": VERSION, "architecture": "win-amd64", "url": ZIP_URL,
        "zip_sha256": EXPECTED_SHA256, "official_sbom_sha256_matches": True,
        "sigstore_bundle_retained": True, "sigstore_cryptographic_verification_performed": False,
        "timestamp": now.isoformat(), "upstream_members": original_members,
        "configured_runtime_members": runtime_members,
        "configuration_change": "Only python314._pth changed; original retained as python314._pth.upstream",
        "driver_status": "NOT_READY_REDISTRIBUTION_LICENSE_UNVERIFIED", "formal_flash_installer": False})
    sentinel = logs / "environment-sentinel"
    sentinel.mkdir()
    (sentinel / "p011_environment_path_must_not_load.py").write_text("raise RuntimeError('environment leak')\n", encoding="ascii")
    env = dict(os.environ, PYTHONHOME=str(sentinel), PYTHONPATH=str(sentinel))
    command = [str(runtime / "python.exe"), "-u", str(BASE / "validate_host.py"), "--output", str(logs / "validation")]
    try:
        child = subprocess.run(command, cwd=sentinel, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, timeout=30)
        stdout, stderr, exit_code, timeout = child.stdout, child.stderr, child.returncode, False
    except subprocess.TimeoutExpired as exc:
        stdout, stderr, exit_code, timeout = exc.stdout or b"", exc.stderr or b"", None, True
    (logs / "host.stdout.raw").write_bytes(stdout)
    (logs / "host.stderr.raw").write_bytes(stderr)
    status = {"scope": "HOST_PORTABLE_RUNTIME_ONLY_NO_DEVICE_IO", "command": command,
              "host_exit": exit_code, "timeout": timeout, "remote_exit": None,
              "remote_exit_applicable": False, "driver_status": "NOT_READY",
              "inventory_called": False, "serial_opened": False, "real_core_called": False}
    write_json(logs / "host.status.json", status)
    print(stdout.decode("utf-8", "replace"), end="", flush=True)
    print(stderr.decode("utf-8", "replace"), end="", file=sys.stderr, flush=True)
    result = logs.with_suffix(".zip")
    with zipfile.ZipFile(result, "x", zipfile.ZIP_DEFLATED) as bundle:
        for file in sorted(logs.rglob("*")):
            if file.is_file():
                bundle.write(file, file.relative_to(logs).as_posix())
        for file in (BASE / "manifest.json", BASE / "build_runtime.py", BASE / "validate_host.py",
                     runtime / "LICENSE.txt", runtime / "python314._pth", runtime / "python314._pth.upstream",
                     sources / "download.records.json"):
            bundle.write(file, "build/" + file.name)
    with zipfile.ZipFile(result) as bundle:
        if bundle.testzip() is not None:
            raise RuntimeError("HOST result ZIP CRC readback failed")
    write_json(BASE / "build-result.json", {"status": status, "host_log_directory": str(logs),
               "host_result_zip": str(result), "host_result_zip_sha256": sha(result.read_bytes()),
               "host_result_zip_crc_verified": True, "runtime_python": str(runtime / "python.exe")})
    print("RESULT_ZIP=" + str(result), flush=True)
    print("RESULT_ZIP_SHA256=" + sha(result.read_bytes()), flush=True)
    return 0 if exit_code == 0 and not timeout else 1


if __name__ == "__main__":
    raise SystemExit(main())
