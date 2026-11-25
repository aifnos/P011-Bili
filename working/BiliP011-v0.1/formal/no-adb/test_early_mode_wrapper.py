"""Three first-run HOST wrapper checks using a fake child, never the core."""

import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import run_early_mode_probe as wrapper


FAKE_CHILD = """import argparse, json, os, pathlib, time
p = argparse.ArgumentParser()
p.add_argument('--output', type=pathlib.Path, required=True)
p.add_argument('--exit-code', type=int, default=0)
p.add_argument('--sleep', type=float, default=0)
a = p.parse_args()
a.output.mkdir(exist_ok=False)
os.write(1, b'ARMED\\r\\n\\x00\\xff\\n')
os.write(2, b'HOST-FAKE-STDERR\\r\\r\\n\\x1b[31mraw\\x00\\xff')
(a.output/'result.json').write_text(json.dumps({'scope':'HOST_FAKE_CHILD_NO_DEVICE'}))
time.sleep(a.sleep)
raise SystemExit(a.exit_code)
"""


class WrapperHostTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p011-wrapper-host-")
        self.addCleanup(self.temporary.cleanup)
        self.base = pathlib.Path(self.temporary.name) / "no-adb"
        self.base.mkdir()
        source_base = pathlib.Path(wrapper.__file__).resolve().parent
        for name in wrapper.SOURCE_NAMES:
            (self.base / name).write_bytes((source_base / name).read_bytes())
        self.fake = self.base / "host_fixture_child.py"
        self.fake.write_text(FAKE_CHILD, encoding="utf-8")
        self.forwarded = io.BytesIO()

    def command(self, base, out, wait, exit_code=0, sleep=0):
        self.assertFalse(out.exists(), "Parent must leave the child output absent")
        return [sys.executable, "-u", str(self.fake), "--output", str(out),
                "--exit-code", str(exit_code), "--sleep", str(sleep)]

    def test_fake_nonzero_exit_raw_streams_and_zip_readback(self):
        with patch.object(wrapper, "_child_command", side_effect=lambda *args: self.command(*args, exit_code=7)):
            result = wrapper.run_probe(1, True, base=self.base, stdout_target=self.forwarded)
        self.assertEqual(result["wrapper_exit"], 7)
        self.assertEqual(result["status"]["host_exit"], 7)
        self.assertFalse(result["status"]["timeout"])
        self.assertTrue(result["status"]["streams_complete"])
        self.assertEqual(result["status"]["watchdog_seconds"], 76)
        self.assertEqual(self.forwarded.getvalue(), b"ARMED\r\n\0\xff\n")
        with zipfile.ZipFile(result["result_zip"]) as bundle:
            self.assertIsNone(bundle.testzip())
            self.assertEqual(bundle.read("host.stdout.raw"), self.forwarded.getvalue())
            self.assertEqual(bundle.read("host.stderr.raw"), b"HOST-FAKE-STDERR\r\r\n\x1b[31mraw\0\xff")
            self.assertEqual(json.loads(bundle.read("device-probe/result.json"))["scope"], "HOST_FAKE_CHILD_NO_DEVICE")
            sources = json.loads(bundle.read("source.sha256.json"))
            self.assertEqual(set(sources["before"]), set(wrapper.SOURCE_NAMES))
            self.assertEqual(sources["before"], sources["after"])
            self.assertFalse(sources["changed_during_run"])
        self.assertTrue(result["crc_readback_verified"])
        self.assertTrue(result["member_sha256_verified"])

    def test_fake_child_timeout_kills_only_that_child_and_archives(self):
        with patch.object(wrapper, "_child_command", side_effect=lambda *args: self.command(*args, sleep=10)), \
             patch.object(wrapper, "_watchdog", return_value=0.2):
            result = wrapper.run_probe(1, True, base=self.base, stdout_target=self.forwarded)
        self.assertEqual(result["wrapper_exit"], 124)
        self.assertTrue(result["status"]["timeout"])
        self.assertTrue(result["status"]["child_kill_attempted"])
        self.assertIsNotNone(result["status"]["host_exit"])
        self.assertIsNone(result["status"]["termination_error"])
        self.assertTrue(result["status"]["streams_complete"])
        self.assertTrue(result["crc_readback_verified"])
        with zipfile.ZipFile(result["result_zip"]) as bundle:
            self.assertTrue(json.loads(bundle.read("host.status.json"))["timeout"])

    def test_lock_conflict_refuses_before_any_child_is_created(self):
        evidence = self.base.parent / "evidence"
        evidence.mkdir()
        # msvcrt byte-region locks are per open handle; this is HOST file I/O.
        with wrapper.ExclusiveLock(evidence / ".early-mode-probe.lock"):
            with patch.object(subprocess, "Popen", side_effect=AssertionError("No child may start")):
                with self.assertRaises(wrapper.LockBusy):
                    wrapper.run_probe(1, True, base=self.base, stdout_target=self.forwarded)
        self.assertEqual([path.name for path in evidence.iterdir()], [".early-mode-probe.lock"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
