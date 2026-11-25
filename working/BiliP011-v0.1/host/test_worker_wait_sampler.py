import ast,pathlib,unittest
from unittest.mock import patch
from worker_wait_sampler import proc_stat,safe_symbol,kernel_symbols,syscall_identity,WorkerWaitSampler
from cached_seek_trial import payload,assess
import test_cached_worker


class WorkerWaitTests(unittest.TestCase):
    def stat(self,start=123,parent=222):
        fields=['0']*50
        for index,value in ((0,'S'),(1,str(parent)),(11,'17'),(12,'3'),(19,str(start)),(36,'2'),(37,'0'),(38,'0')):
            fields[index]=value
        return '123 (nested ) name) '+' '.join(fields)

    def test_stat_fields_not_comm_content(self):
        value=proc_stat(self.stat())
        self.assertEqual(value,dict(state='S',parent=222,user=17,system=3,start=123,cpu=2,priority=0,policy=0))
        for value in ('123 bad','1 (bad) S 1','1 (long) '+('0 '*5000)):
            with self.assertRaises(ValueError):proc_stat(value)

    def test_only_kernel_function_names_leave_stack(self):
        raw='[<deadbeef>] vsp_ioctl+0x18/0x70\n[<abc01234>] wait_event+0x00/0x88\nhttps://private/?token=x'
        self.assertEqual(kernel_symbols(raw),['vsp_ioctl','wait_event'])
        self.assertEqual(safe_symbol('/private?key=value'),'other')
        self.assertEqual(safe_symbol('omxh264dec-omx'),'omxh264dec-omx')

    def test_syscall_keeps_no_pointer_or_arbitrary_ioctl_data(self):
        def vsp(fd):
            self.assertEqual(fd,28)
            return '/dev/sprd_vsp'
        raw='54 0x1c 0x6d07 0xdeadbeef 0xf1235678'
        self.assertEqual(syscall_identity(raw,vsp),'vsp_poll_complete')
        self.assertEqual(syscall_identity(raw,lambda fd:'/dev/ion'),'syscall_54')
        self.assertEqual(syscall_identity(raw.replace('0x6d07','0x6d05'),vsp),'vsp_acquire')
        self.assertEqual(syscall_identity('240 0xabcdef',vsp),'syscall_240')
        self.assertEqual(syscall_identity('-1 0xabcdef',vsp),'not_in_syscall')
        self.assertEqual(syscall_identity('running',vsp),'running')

    def test_invalid_target_rejected_before_start(self):
        for parent,path in ((1,'/mnt/data/p011-toolbox/bili-seek-probe-'+'a'*24),(22,'/usr/bin'),(22,'/mnt/data/p011-toolbox/bili-seek-probe-'+'a'*24+'/../stock')):
            with self.assertRaises(ValueError):WorkerWaitSampler(parent,path)

    def test_python35_source_and_no_mutation_api(self):
        raw=pathlib.Path(__file__).with_name('worker_wait_sampler.py').read_text()
        tree=ast.parse(raw,feature_version=(3,5));ast.parse(payload(),feature_version=(3,5))
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='open':
                self.assertEqual(node.args[1].value,'r')
        for forbidden in ('subprocess','os.kill','chmod','ptrace'):
            self.assertNotIn(forbidden,raw)
        literals='\n'.join(node.value for node in ast.walk(tree) if isinstance(node,ast.Constant) and isinstance(node.value,str))
        for forbidden in ('/mem','/environ','/cmdline'):
            self.assertNotIn(forbidden,literals)
        self.assertIn("finally:\n  if sampler is not None:report['wait_sample']=sampler.finish()",payload())

    def test_driver_and_worker_reuse_rejected(self):
        sampler=WorkerWaitSampler.__new__(WorkerWaitSampler)
        sampler.parent=222;sampler.parent_start=10;sampler.pid=333;sampler.start_time=20
        sampler.executable='/mnt/data/p011-toolbox/bili-seek-probe-'+'a'*24+'/bili-hw'
        with patch('worker_wait_sampler.bounded_read',return_value=self.stat(start=11)):
            with self.assertRaises(ValueError):sampler.exact_worker()
        with patch('worker_wait_sampler.bounded_read',side_effect=[self.stat(start=10),self.stat(start=21)]):
            with self.assertRaises(ValueError):sampler.exact_worker()
        with patch('worker_wait_sampler.bounded_read',side_effect=[self.stat(start=10),self.stat(start=20)]),patch('worker_wait_sampler.os.readlink',return_value='/usr/bin/Z03'):
            with self.assertRaises(ValueError):sampler.exact_worker()

    def test_sample_gate_cannot_replace_performance_result(self):
        report=test_cached_worker.CachedWorkerTests().fixture()
        self.assertFalse(assess(report,'cached','throughput',True)['passed'])
        report['wait_sample']=dict(joined=True,worker_observed=True,identity_rejected=False,samples=16,threads={})
        self.assertFalse(assess(report,'cached','throughput',True)['passed'])
        report['wait_sample']['threads']={'1_10':dict(samples=16)}
        report['probe']['rate']['consumed_fps']=52
        result=assess(report,'cached','throughput',True)
        self.assertTrue(result['passed'])
        self.assertFalse(result['unclocked_rate_meets_source'])
        self.assertFalse(result['playback_passed'])

    def test_discovery_without_checkpoint_restore_stays_ppid_bound(self):
        sampler=WorkerWaitSampler.__new__(WorkerWaitSampler)
        sampler.parent=222;sampler.parent_start=10;sampler.pid=None;sampler.start_time=None
        sampler.executable='/mnt/data/p011-toolbox/bili-seek-probe-'+'a'*24+'/bili-hw'
        sampler.result=dict(children_interface=True)
        def read(path):
            return self.stat(start=10,parent=1) if path=='/proc/222/stat' else self.stat(start=20,parent=222)
        with patch('worker_wait_sampler.bounded_read',side_effect=read),patch('worker_wait_sampler.os.path.exists',return_value=False),patch('worker_wait_sampler.os.listdir',return_value=['222','333','self']),patch('worker_wait_sampler.os.readlink',return_value=sampler.executable):
            self.assertTrue(sampler.exact_worker())
            self.assertEqual((sampler.pid,sampler.start_time),(333,20))
            self.assertFalse(sampler.result['children_interface'])


if __name__=='__main__':unittest.main()
