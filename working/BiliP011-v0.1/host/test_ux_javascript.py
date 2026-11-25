"""Run the exact QML JavaScript helpers, not a translated Python model."""
import pathlib
import shutil
import subprocess
import unittest

class JavascriptTests(unittest.TestCase):
    def test_bounded_queues_and_input_protocol(self):
        node=shutil.which('node')
        self.assertIsNotNone(node,'Node is required for the QML JavaScript regression')
        base=pathlib.Path(__file__).resolve().parent
        for script in ('test_bili_ux.js','test_player_automation.js'):
            result=subprocess.run([node,str(base/script)],capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue('"passed":true' in result.stdout or result.stdout.startswith('PASS:'))
