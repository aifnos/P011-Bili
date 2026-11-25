"""Host-only transport, syntax, isolation and no-write checks for the audit."""
import ast
import base64
import hashlib
import pathlib
import shlex
import unittest
import zlib
from feature_feasibility_audit import GROUPS, remote_code

BASE = pathlib.Path(__file__).resolve().parents[1]
BUNDLE = BASE/'out/awake-62d57bbf852d0faf15d2de6d'


class AuditChecks(unittest.TestCase):
    def code(self, group):
        hashes={name:hashlib.sha256((BUNDLE/name).read_bytes()).hexdigest()
                for name in ('stdlib-json35.zip','native_safety.py')}
        return remote_code(group,'/mnt/data/p011-toolbox/bili-awake/62d57bbf852d0faf15d2de6d',hashes)

    def test_python35_and_legacy_transport(self):
        for group in GROUPS:
            with self.subTest(group=group):
                code=self.code(group)
                ast.parse(code,feature_version=(3,5))
                packed=base64.b64encode(zlib.compress(code.encode(),9)).decode()
                loader='import base64,zlib;exec(zlib.decompress(base64.b64decode('+repr(packed)+')))'
                command='(python3 -B -c '+shlex.quote(loader)+'); rc=$?; printf "\\n__REMOTE_EXIT__=%s\\n" "$rc"'
                self.assertLess(len(command.encode()),4096)

    def test_no_account_write_or_player_command(self):
        for group in GROUPS:
            with self.subTest(group=group):
                code=self.code(group)
                for forbidden in ('--data','--request','--location','--insecure','--cookie-jar','archive/like','coin/add','resource/deal','toview/add','toview/del','relation/modify','web/heartbeat','bili-player','gst-launch'):
                    self.assertNotIn(forbidden,code)
                self.assertIn('require_stock(before)',code)
                self.assertIn('require_stock(after)',code)
                self.assertIn('original_cookie == cookie_hash()',code)

    def test_groups_do_not_leak_into_each_other(self):
        self.assertNotIn('folder_videos',self.code('public'))
        self.assertNotIn('live_home',self.code('account'))
        self.assertNotIn('subtitle_body',self.code('live'))
        self.assertIn('timed_text_valid',self.code('subtitles'))

    def test_no_unknown_group(self):
        with self.assertRaises(ValueError):remote_code('write','',{})


if __name__=='__main__':unittest.main(verbosity=2)
