"""Synthetic host fixtures only: no Wayland, ADB, Docker or physical claims."""
import json
import unittest
from wayland_evidence import analyze, probe_passed, MAX_EVENTS, MAX_TRACE_CHARS

ROLE = '[1] -> zxdg_shell_v6@13.get_xdg_surface(new id zxdg_surface_v6@24, wl_surface@23)\n'
EMPTY = '[2] -> wl_surface@23.commit()\n'
CONFIGURE = '[3] zxdg_surface_v6@24.configure(17)\n'
ACK = '[4] -> zxdg_surface_v6@24.ack_configure(17)\n'
ATTACH = '[5] -> wl_surface@23.attach(wl_buffer@27, 0, 0)\n'
COMMIT = '[6] -> wl_surface@23.commit()\n'
VALID = ROLE+EMPTY+CONFIGURE+ACK+ATTACH+COMMIT


class WaylandEvidenceTests(unittest.TestCase):
    def test_complete_handshake(self):
        self.assertTrue(analyze(VALID)['passed'])

    def test_multiple_pending_configures_preserve_later_serial(self):
        extra_config=CONFIGURE.replace('(17)','(18)')
        extra_ack=ACK.replace('(17)','(18)')
        self.assertTrue(analyze(ROLE+EMPTY+CONFIGURE+extra_config+ACK+extra_ack+ATTACH+COMMIT)['passed'])

    def test_serial_zero_and_wrap_are_valid(self):
        self.assertTrue(analyze(VALID.replace('(17)','(0)'))['passed'])
        self.assertTrue(analyze(VALID.replace('(17)','(4294967295)'))['passed'])

    def test_out_of_range_role_rejected(self):
        self.assertFalse(analyze(VALID.replace('surface_v6@24','surface_v6@4294967296'))['passed'])

    def test_stable_xdg_also_supported(self):
        stable = VALID.replace('zxdg_shell_v6','xdg_wm_base').replace('zxdg_surface_v6','xdg_surface')
        self.assertTrue(analyze(stable)['passed'])

    def test_sync_callback_is_not_configure(self):
        trace = ROLE+EMPTY+'[3] wl_callback@27.done(218)\n'+ATTACH+COMMIT
        result = analyze(trace)
        self.assertFalse(result['passed'])
        self.assertEqual(result['status'],'unconfigured_buffer_commit')

    def test_ack_without_received_serial_rejected(self):
        self.assertFalse(analyze(ROLE+EMPTY+ACK+ATTACH+COMMIT)['passed'])

    def test_wrong_serial_rejected(self):
        self.assertFalse(analyze(VALID.replace('ack_configure(17)','ack_configure(18)'))['passed'])

    def test_late_configure_does_not_retroactively_pass(self):
        self.assertFalse(analyze(ROLE+EMPTY+ATTACH+COMMIT+CONFIGURE+ACK)['passed'])

    def test_other_surfaces_do_not_supply_ack(self):
        trace = ROLE+EMPTY+CONFIGURE.replace('@24','@99')+ACK.replace('@24','@99')+ATTACH+COMMIT
        self.assertFalse(analyze(trace)['passed'])

    def test_no_initial_empty_commit_rejected(self):
        self.assertFalse(analyze(ROLE+CONFIGURE+ACK+ATTACH+COMMIT)['passed'])

    def test_null_buffer_commit_not_a_draw(self):
        result=analyze(ROLE+EMPTY+CONFIGURE+ACK+ATTACH.replace('wl_buffer@27','nil')+COMMIT)
        self.assertEqual(result['status'],'no_buffer_commit')

    def test_two_xdg_windows_ambiguous(self):
        self.assertEqual(analyze(VALID+ROLE.replace('@24','@28'))['status'],'missing_or_ambiguous_role')

    def test_privacy_allowlist_and_error_reject(self):
        private = ('[7] wl_keyboard@16.key(1, 2, 3, 4)\n'
                   '[8] -> zxdg_toplevel_v6@25.set_title("PRIVATE_TITLE")\n'
                   '[9] wl_display@1.error(zxdg_surface_v6@24, 3, "PRIVATE_ERROR")\n')
        result=analyze(VALID+private)
        self.assertFalse(result['passed'])
        self.assertEqual(result['status'],'display_protocol_error')
        for forbidden in ('PRIVATE', 'keyboard', 'key(', 'title'):
            self.assertNotIn(forbidden,json.dumps(result))

    def test_bounded_evidence(self):
        self.assertEqual(analyze('x'*(MAX_TRACE_CHARS+1))['status'],'trace_size_rejected')
        self.assertEqual(analyze(ROLE+EMPTY*MAX_EVENTS)['status'],'event_limit_rejected')

    def test_direction_matters(self):
        self.assertFalse(analyze(VALID.replace('[3] zxdg','[3] -> zxdg'))['passed'])
        self.assertFalse(analyze(VALID.replace('[4] -> zxdg','[4] zxdg'))['passed'])

    def test_only_owned_role_commits_count(self):
        self.assertFalse(analyze(ROLE+CONFIGURE+ACK+EMPTY.replace('@23','@17')+ATTACH+COMMIT)['passed'])

    def test_missing_trace_is_not_success(self):
        self.assertFalse(analyze('')['passed'])

    def test_all_gates_required(self):
        report={'probe':{'passed':True,'frames':200,'rgba_bits':[8]*4,'gl_error':0,'drawable':[800,268]},
                'process':{'exit':0,'timeout':False},'stock_unchanged':True,'protocol_audit':analyze(VALID)}
        self.assertTrue(probe_passed(report))
        for key in ('probe','process','stock_unchanged','protocol_audit'):
            changed=dict(report);changed.pop(key)
            self.assertFalse(probe_passed(changed))
        for key,value in (('frames',1),('rgba_bits',[4]*4),('gl_error',1285),('drawable',[800,480])):
            changed=dict(report,probe=dict(report['probe'],**{key:value}))
            self.assertFalse(probe_passed(changed))


if __name__=='__main__':unittest.main()
