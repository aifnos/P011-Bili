import re,unittest
from test_client import BASE
from client_results import CAPTURES
class CaptureContractTests(unittest.TestCase):
    def test_all_player_captures_have_native_allowlist(self):
        text=(BASE/'client/player_v2.cpp').read_text(encoding='utf-8')
        native=set(re.findall(r'"(player-[a-z0-9-]+)"',text.split('static void save_capture(',1)[1].split(';',1)[0]))
        self.assertEqual(native,{n for n in CAPTURES if n.startswith('player-')})
    def test_private_live_info_not_a_public_job(self):
        import service
        self.assertNotIn('live_danmaku_info',service.PUBLIC_OPS)
