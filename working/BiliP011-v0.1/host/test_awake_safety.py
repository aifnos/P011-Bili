"""PC mocks for exact identity/recovery helpers, never imports target config."""
import importlib.util
import pathlib
import sys
import types
import unittest
from unittest.mock import patch

BASE=pathlib.Path(__file__).resolve().parents[1]
NATIVE=BASE.parents[1]/'working/ToolboxNext-v0.5.1-native'
sys.path.insert(0,str(NATIVE/'runtime'))
sys.modules['config']=types.SimpleNamespace()
spec=importlib.util.spec_from_file_location('awake_under_test',BASE/'runtime/awake_trial.py')
t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)


class Safety(unittest.TestCase):
    def row(self,**values):
        r=dict(pid=23456,start='80',exe='/private/candidate',state='S',parent=1,sid=23456,threads=1,args=[])
        r.update(values);return r

    def test_signal_exact_identity(self):
        row=self.row()
        with patch.object(t,'proc',return_value=row),patch.object(t.os,'kill') as kill:
            self.assertTrue(t.send(row,t.signal.SIGTERM));kill.assert_called_once_with(row['pid'],t.signal.SIGTERM)

    def test_reused_pid_is_never_signalled(self):
        with patch.object(t,'proc',return_value=self.row(start='81')),patch.object(t.os,'kill') as kill:
            self.assertFalse(t.send(self.row(),t.signal.SIGTERM));kill.assert_not_called()

    def test_same_start_changed_executable_refused(self):
        with patch.object(t,'proc',return_value=self.row(exe='/other')),patch.object(t.os,'kill') as kill:
            with self.assertRaises(RuntimeError):t.send(self.row(),t.signal.SIGTERM)
            kill.assert_not_called()

    def test_zombie_is_not_signalled(self):
        with patch.object(t,'proc',return_value=self.row(state='Z')),patch.object(t.os,'kill') as kill:
            self.assertFalse(t.send(self.row(),t.signal.SIGTERM));kill.assert_not_called()

    def test_missing_process_is_not_signalled(self):
        with patch.object(t,'proc',return_value=None),patch.object(t.os,'kill') as kill:
            self.assertFalse(t.send(self.row(),t.signal.SIGTERM));kill.assert_not_called()

    def test_init_never_signalled(self):
        with patch.object(t,'proc',return_value=self.row(pid=1)),patch.object(t.os,'kill') as kill:
            with self.assertRaises(RuntimeError):t.send(self.row(pid=1),t.signal.SIGTERM)
            kill.assert_not_called()

    def test_original_no_sigkill_after_timeout(self):
        row=self.row(exe='/usr/bin/Z03')
        with patch.object(t,'send',return_value=True) as send,patch.object(t,'refresh',return_value=row),patch.object(t.time,'monotonic',side_effect=[0,6]),patch.object(t.time,'sleep'):
            with self.assertRaises(RuntimeError):t.terminate(row,kill=False)
            send.assert_called_once_with(row,t.signal.SIGTERM)

    def test_shutdown_grace_rejects_unbounded_values_before_signal(self):
        for grace in (0, 1, 30, 600, -1, None):
            with patch.object(t,'send') as send:
                with self.assertRaises(ValueError):t.terminate(self.row(),kill=True,grace=grace)
                send.assert_not_called()

    def test_service_has_time_to_release_hardware_without_force(self):
        row=self.row()
        with patch.object(t,'send',return_value=True) as send, \
             patch.object(t,'refresh',side_effect=[row,None,None,None]), \
             patch.object(t.time,'monotonic',side_effect=[0,10]),patch.object(t.time,'sleep'):
            t.terminate(row,kill=True,grace=15)
            send.assert_called_once_with(row,t.signal.SIGTERM)

    def test_release_is_explicit_inactive(self):
        with patch.object(t.C,'SESSION','testsession',create=True),patch.object(t,'atomic') as atomic:
            t.release()
            name,body=atomic.call_args.args
            self.assertEqual(name,'lease.json');self.assertIn('"active": false',body);self.assertIn('testsession',body)

    def test_syntax_target_python_35(self):
        import ast
        ast.parse((BASE/'runtime/awake_trial.py').read_text(),feature_version=(3,5))

    def test_client_cleanup_is_scoped_to_exact_session(self):
        media='/mnt/data/p011-toolbox/bili-media/test'
        service=self.row(pid=300,exe='/usr/bin/python3',args=['python3','-B',t.ROOT+'/service.py'])
        ours=self.row(pid=301,exe=media+'/bin/bili-hw')
        other=self.row(pid=302,exe=media+'/bin/bili-player')
        stock=self.row(pid=303,exe='/usr/bin/Z03')
        remaining=[other,stock]
        with patch.object(t.C,'CLIENT',True,create=True),patch.object(t.C,'MEDIA',media,create=True), \
             patch.object(t,'procs',side_effect=[[service,ours,other,stock],remaining,remaining,remaining]), \
             patch.object(t,'environment',side_effect=lambda r:{'P011_CLIENT_ROOT':t.ROOT if r['pid']==301 else '/different-session'}), \
             patch.object(t,'saved',side_effect=lambda name:service if name=='bili-service' else None), \
             patch.object(t,'terminate') as terminate,patch.object(t,'release') as release:
            t.cleanup_private()
            signalled=[call.args[0]['pid'] for call in terminate.call_args_list if call.args[0]]
            self.assertEqual(set(signalled),{300,301})
            self.assertEqual(terminate.call_args_list[0].kwargs,{'kill':True,'grace':15})
            release.assert_called_once()

    def test_client_cleanup_refuses_to_claim_recovery_with_residue(self):
        media='/mnt/data/p011-toolbox/bili-media/test'
        ours=self.row(pid=301,exe=media+'/bin/bili-player')
        with patch.object(t.C,'CLIENT',True,create=True),patch.object(t.C,'MEDIA',media,create=True), \
             patch.object(t,'procs',return_value=[ours]), \
             patch.object(t,'environment',return_value={'P011_CLIENT_ROOT':t.ROOT}), \
             patch.object(t,'saved',return_value=None),patch.object(t,'terminate'),patch.object(t,'release') as release:
            with self.assertRaisesRegex(RuntimeError,'remains active'):t.cleanup_private()
            release.assert_not_called()


if __name__=='__main__':unittest.main(verbosity=2)
