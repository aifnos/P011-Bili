"""Archive one explicitly permitted early-mode probe with a HOST watchdog.

This wrapper issues no device commands. It launches only the sibling core,
keeps its exact output streams, and kills only its own Popen child on timeout.
Importing this module neither runs the core nor opens a device.
"""

import argparse
import datetime
import errno
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import threading
import time
import uuid
import zipfile


SOURCE_NAMES = ("early_mode_probe.py", "bsl_frames.py",
                "win32_download_transport.py", "run_early_mode_probe.py")


class LockBusy(RuntimeError):
    pass


class ExclusiveLock:
    """One-byte msvcrt lock; keep the persistent lock file to avoid unlink races."""

    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.file = None

    def __enter__(self):
        import msvcrt
        handle = self.path.open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise LockBusy("Another early-mode probe is already running") from exc
                raise
        except BaseException:
            handle.close()
            raise
        self.file = handle
        return self

    def __exit__(self, kind, value, trace):
        import msvcrt
        if self.file is not None:
            handle, self.file = self.file, None
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            finally:
                handle.close()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _child_command(base, child_out, wait_seconds):
    return [sys.executable, "-u", str(base / "early_mode_probe.py"),
            "--permit-mode-selection", "--wait-seconds", str(wait_seconds),
            "--output", str(child_out)]


def _watchdog(wait_seconds):
    return wait_seconds + 75


def _capture(command, run_dir, watchdog_seconds, stdout_target=None):
    """Capture one child; deliberately accepts a fake command for HOST fixtures."""
    if stdout_target is None:
        stdout_target = getattr(sys.stdout, "buffer", sys.stdout)
    paths = {name: run_dir / ("host." + name + ".raw") for name in ("stdout", "stderr")}
    for path in paths.values():
        path.write_bytes(b"")
    status = {"host_exit": None, "remote_exit": None, "remote_exit_applicable": False,
              "timeout": False, "interrupted": False, "child_kill_attempted": False,
              "watchdog_seconds": watchdog_seconds, "capture_errors": [],
              "stdout_forward_errors": [], "streams_complete": False,
              "spawn_error": None, "termination_error": None}
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
    try:
        child = subprocess.Popen(command, cwd=str(run_dir), stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 env=env, close_fds=True,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as exc:
        status["spawn_error"] = type(exc).__name__ + ": " + str(exc)
        return status

    capture_failed = threading.Event()

    def pump(name, stream):
        try:
            with paths[name].open("wb") as raw:
                while True:
                    chunk = stream.read1(4096)
                    if not chunk:
                        break
                    raw.write(chunk)
                    raw.flush()
                    if name == "stdout":
                        try:
                            if isinstance(stdout_target, (type(sys.stdout),)) and not hasattr(stdout_target, "buffer"):
                                stdout_target.write(chunk.decode("utf-8", "replace"))
                            else:
                                stdout_target.write(chunk)
                            stdout_target.flush()
                        except (OSError, ValueError, TypeError) as exc:
                            status["stdout_forward_errors"].append(type(exc).__name__ + ": " + str(exc))
        except (OSError, ValueError) as exc:
            status["capture_errors"].append(name + ": " + type(exc).__name__ + ": " + str(exc))
            capture_failed.set()
        finally:
            stream.close()

    threads = [threading.Thread(target=pump, args=(name, stream), daemon=True)
               for name, stream in (("stdout", child.stdout), ("stderr", child.stderr))]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + watchdog_seconds
    try:
        while child.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                status["timeout"] = True
                break
            if capture_failed.is_set():
                break
            try:
                child.wait(timeout=min(0.1, remaining))
            except subprocess.TimeoutExpired:
                pass
    except KeyboardInterrupt:
        status["interrupted"] = True
    finally:
        if child.poll() is None:
            status["child_kill_attempted"] = True
            try:
                child.kill()  # Exact child process handle; never taskkill/process-name scans.
                child.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired) as exc:
                status["termination_error"] = type(exc).__name__ + ": " + str(exc)
        status["host_exit"] = child.poll()
        for thread in threads:
            thread.join(timeout=5)
        status["streams_complete"] = not any(thread.is_alive() for thread in threads)
    return status


def _archive(run_dir):
    # Freeze member bytes once so CRC and SHA readback verify the exact snapshot.
    members = {}
    for path in sorted(run_dir.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("Refusing a symbolic link in probe evidence")
        if path.is_file():
            members[path.relative_to(run_dir).as_posix()] = path.read_bytes()
    manifest = {name: _sha(data) for name, data in members.items()}
    members["archive.manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    archive = run_dir.with_suffix(".zip")
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as bundle:
        for name, data in members.items():
            bundle.writestr(name, data)
    with zipfile.ZipFile(archive, "r") as bundle:
        if bundle.testzip() is not None or set(bundle.namelist()) != set(members):
            raise RuntimeError("Probe ZIP CRC/member readback failed")
        for name, expected in members.items():
            if _sha(bundle.read(name)) != _sha(expected):
                raise RuntimeError("Probe ZIP SHA-256 readback failed")
    return archive, _sha(archive.read_bytes())


def run_probe(wait_seconds=300, permit_mode_selection=False, *, base=None, stdout_target=None):
    """Run the fixed sibling core; permit is mandatory even through this API."""
    if permit_mode_selection is not True:
        raise ValueError("Explicit --permit-mode-selection is required")
    if type(wait_seconds) is not int or not 1 <= wait_seconds <= 600:
        raise ValueError("--wait-seconds must be an integer from 1 through 600")
    base = pathlib.Path(__file__).resolve().parent if base is None else pathlib.Path(base).resolve()
    evidence_root = base.parent / "evidence"
    evidence_root.mkdir(parents=True, exist_ok=True)
    with ExclusiveLock(evidence_root / ".early-mode-probe.lock"):
        now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
        run_dir = evidence_root / ("early-mode-probe-" + now.strftime("%Y%m%d-%H%M%S-%f") + "-" + uuid.uuid4().hex[:8])
        run_dir.mkdir(exist_ok=False)
        child_out = run_dir / "device-probe"  # The core must create this directory itself.
        snapshot = run_dir / "sources"
        snapshot.mkdir()
        before = {}
        for name in SOURCE_NAMES:
            data = (base / name).read_bytes()
            before[name] = _sha(data)
            (snapshot / name).write_bytes(data)
        command = _child_command(base, child_out, wait_seconds)
        print("LOG_DIR=" + str(run_dir), flush=True)
        _json(run_dir / "command.json", {"argv": command, "wait_seconds": wait_seconds,
              "permit_mode_selection": True, "child_output_directory": "device-probe",
              "wrapper_device_commands": False})
        status = _capture(command, run_dir, _watchdog(wait_seconds), stdout_target)
        after = {name: _sha((base / name).read_bytes()) for name in SOURCE_NAMES}
        changed = before != after
        _json(run_dir / "source.sha256.json", {"before": before, "after": after,
                                               "changed_during_run": changed})
        if status["interrupted"]:
            exit_code = 130
        elif status["timeout"]:
            exit_code = 124
        elif (changed or not status["streams_complete"] or status["capture_errors"] or
              status["stdout_forward_errors"] or status["spawn_error"] or status["termination_error"]):
            exit_code = 1
        else:
            exit_code = status["host_exit"] if status["host_exit"] is not None else 1
        status.update(wrapper_exit=exit_code, source_changed=changed,
                      scope="HOST_WRAPPER_CORE_OUTCOME_SEPARATE", timestamp=now.isoformat())
        _json(run_dir / "host.status.json", status)
        try:
            archive, archive_sha256 = _archive(run_dir)
        except Exception as exc:
            _json(run_dir / "archive.failure.json", {"error": type(exc).__name__ + ": " + str(exc)})
            raise
        verified = {"result_zip": str(archive), "zip_sha256": archive_sha256,
                    "crc_readback_verified": True, "member_sha256_verified": True,
                    "wrapper_exit": exit_code}
        _json(run_dir / "archive.verification.json", verified)
        print("RESULT_ZIP=" + str(archive), flush=True)
        print("RESULT_ZIP_SHA256=" + archive_sha256, flush=True)
        print("ZIP_READBACK_VERIFIED=true", flush=True)
        return dict(verified, run_directory=str(run_dir), status=status)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Explicitly permitted early-mode probe plus raw evidence ZIP")
    parser.add_argument("--permit-mode-selection", action="store_true")
    parser.add_argument("--wait-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    if not args.permit_mode_selection:
        parser.error("active boot mode request requires explicit --permit-mode-selection")
    if not 1 <= args.wait_seconds <= 600:
        parser.error("--wait-seconds must be from 1 through 600")
    try:
        result = run_probe(args.wait_seconds, args.permit_mode_selection)
    except LockBusy as exc:
        print(str(exc) + "; no other process was stopped", file=sys.stderr, flush=True)
        return 2
    except (OSError, RuntimeError, ValueError) as exc:
        print("Wrapper failed: " + type(exc).__name__ + ": " + str(exc), file=sys.stderr, flush=True)
        return 1
    return result["wrapper_exit"]


if __name__ == "__main__":
    raise SystemExit(main())
