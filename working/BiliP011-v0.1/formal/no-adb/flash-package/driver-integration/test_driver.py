"""Host checks; no UAC, driver install, USB open or device transaction."""
import contextlib
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).parent))
sys.path.insert(1, str(pathlib.Path(__file__).parents[1] / 'out/P011-Bili-NoADB-v1-final-20261014/app'))
import driver_setup as driver
import run


class DriverChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(mock.patch.object(driver, 'check_host'))
        self.bundle = self.stack.enter_context(mock.patch.object(driver, 'verify_driver_bundle', return_value=self.root))
        self.install = self.stack.enter_context(mock.patch.object(driver, 'install_driver', side_effect=AssertionError('native install prohibited in test')))
        self.admin = self.stack.enter_context(mock.patch.object(driver, 'is_admin', return_value=False))
        self.elevate = self.stack.enter_context(mock.patch.object(driver, 'elevate_helper', side_effect=AssertionError('UAC prohibited in test')))

    def test_already_registered_never_elevates_or_installs(self):
        with mock.patch.object(driver, 'registered_driver', return_value={'published_inf': 'oem14.inf'}):
            self.assertEqual(driver.ensure_driver(self.root / 'driver'), 0)
        self.install.assert_not_called()
        self.elevate.assert_not_called()
        self.admin.assert_not_called()

    def test_cancel_uac_records_failure(self):
        self.elevate.side_effect = None
        self.elevate.return_value = 1223
        with mock.patch.object(driver, 'registered_driver', return_value=None):
            self.assertEqual(driver.ensure_driver(self.root / 'driver'), 1223)
        result = json.loads((self.root / 'driver/driver-result.json').read_text(encoding='utf-8'))
        self.assertEqual(result['status'], 'DRIVER_NOT_READY')

    def test_success_must_recheck_registration(self):
        self.elevate.side_effect = None
        self.elevate.return_value = 0
        with mock.patch.object(driver, 'registered_driver', side_effect=[None, {'published_inf': 'oem14.inf'}]) as found:
            self.assertEqual(driver.ensure_driver(self.root / 'driver'), 0)
            self.assertEqual(found.call_count, 2)

    def test_exit_zero_without_registered_files_fails(self):
        self.elevate.side_effect = None
        self.elevate.return_value = 0
        with mock.patch.object(driver, 'registered_driver', return_value=None):
            self.assertEqual(driver.ensure_driver(self.root / 'driver'), 1)

    def test_bad_driver_bytes_fail_before_uac(self):
        self.bundle.side_effect = RuntimeError('bad driver hash')
        with mock.patch.object(driver, 'registered_driver') as found:
            with self.assertRaisesRegex(RuntimeError, 'bad driver'):
                driver.ensure_driver(self.root / 'driver')
        found.assert_not_called()
        self.elevate.assert_not_called()

    def test_failure_cancel_timeout_and_restart_never_flash(self):
        for code in (1, 1223, 124, 3010):
            with self.subTest(code=code), mock.patch.object(run, 'ensure_driver', return_value=code), mock.patch.object(run, '_capture') as capture, mock.patch('builtins.input') as prompt:
                self.assertEqual(run.workflow('install', self.root), code)
                capture.assert_not_called()
                prompt.assert_not_called()

    def test_driver_only_mode_never_opens_device(self):
        with mock.patch.object(run, 'ensure_driver', return_value=0), mock.patch.object(run, '_capture') as capture, mock.patch('builtins.input') as prompt:
            self.assertEqual(run.workflow('driver', self.root), 0)
        capture.assert_not_called()
        prompt.assert_not_called()

    def test_ready_then_prompt_then_fixed_flash_command(self):
        order = []
        def ready(output):
            order.append('driver')
            return 0
        def prompt():
            order.append('prompt')
            return ''
        def capture(command, output, timeout):
            order.append('capture')
            self.assertEqual(command[-3:], ['restore', '--output', str(self.root)])
            self.assertEqual(timeout, 10800)
            return dict(interrupted=False, timeout=False, capture_errors=[], stdout_forward_errors=[],
                spawn_error=None, termination_error=None, streams_complete=True, host_exit=0)
        with mock.patch.object(run, 'ensure_driver', side_effect=ready), mock.patch.object(run, '_capture', side_effect=capture), mock.patch('builtins.input', side_effect=prompt):
            self.assertEqual(run.workflow('restore', self.root), 0)
        self.assertEqual(order, ['driver', 'prompt', 'capture'])

    def test_check_mode_is_files_only(self):
        with mock.patch.object(sys, 'argv', ['run.py', 'check']), mock.patch.object(run, 'verify_package'), mock.patch.object(run, 'ensure_driver') as ensure:
            self.assertEqual(run.main(), 0)
        ensure.assert_not_called()


class InstallCommandChecks(unittest.TestCase):
    def test_exact_inf_stage_only_and_reboot_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary)
            with mock.patch.object(driver, 'check_host'), mock.patch.object(driver, 'verify_package'), mock.patch.object(driver, 'verify_driver_bundle', return_value=output), mock.patch.object(driver, 'is_admin', return_value=True), mock.patch.object(driver, 'system_directory', return_value=output), mock.patch.object(driver, 'registered_driver') as found, mock.patch.object(driver.subprocess, 'run', return_value=subprocess.CompletedProcess([], 3010)) as process:
                self.assertEqual(driver.install_driver(output), 3010)
                command = process.call_args.args[0]
                self.assertEqual(command, [str(output / 'pnputil.exe'), '/add-driver', str(output / 'sprdvcom.inf')])
                found.assert_not_called()
                self.assertTrue(json.loads((output / 'driver-helper-result.json').read_text())['reboot_requested'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
