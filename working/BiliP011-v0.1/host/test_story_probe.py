import ast
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch
from test_client import service,BASE
from build_awake_trial import build
from story_probe import handle,CHECKS

class StoryProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
    def test_builder_is_explicit_and_isolated(self):
        options=dict(client=True,automated=True,player_protocol=2,ux_state=True,story_probe=True)
        for change in ({'automated':False},{'client':False},{'ux_state':False},{'player_protocol':1},
                       {'catalog_probe':True},{'feature_probe':True},{'ux_probe':True},{'screen_check':True},
                       {'toolbox':True},{'benchmark_quality':32},{'demo_seconds':180},{'story_probe':1}):
            with self.assertRaises(ValueError):build(None,**dict(options,**change))
    def test_observation_requires_real_cache_hit_and_active_playback(self):
        p=dict(active=True,switch_pending=False,hardware_verified=True,muted=True)
        b=type('Backend',(),dict(root=self.tmp.name,story_probe=True,automation=True,qa_claimed=True,qa_finished=False,protocol=2,story_rounds=[]))()
        b.state=lambda:dict(player=p)
        handle(b,dict(phase='observe'),lambda x:True)
        with self.assertRaises(ValueError):handle(b,dict(phase='observe'),lambda x:True)
        p.update(cached_media=True,prefetch_media_hits=1);handle(b,dict(phase='observe'),lambda x:True)
        p['active']=False
        with self.assertRaises(ValueError):handle(b,dict(phase='observe'),lambda x:True)
    def test_route_not_available_in_normal_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=service.Backend(tmp,'','',tmp,{},helper=lambda op,a:{})
            try:
                with self.assertRaises(service.Failure):b.ux_state_check(dict(phase='observe'))
            finally:b.close()
    def test_python35_and_no_credential_ops(self):
        for name in ('story_probe.py','media_relay.py','story_cache.py'):ast.parse((BASE/'client'/name).read_text(encoding='utf-8'),feature_version=(3,5))
        qml=(BASE/'client/BiliStoryAutomation.qml').read_text(encoding='utf-8')
        self.assertIn('shot.grabImage(target.Window.window.contentItem)',qml)
        self.assertNotIn('target.grabToImage',qml)
        for name in ('qr_new','qr_poll','interaction','watch_heartbeat','password_login'):self.assertNotIn('"'+name+'"',qml)

if __name__=='__main__':unittest.main()
