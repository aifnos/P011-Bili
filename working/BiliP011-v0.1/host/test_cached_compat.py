import ast
import copy
import importlib.util
import pathlib
import subprocess
import sys
import unittest
from cached_seek_trial import payload,assess
from cached_compat_evidence import evaluate
from cached_worker_audit import audit_row
from worker_wait_audit import inspect_result
import test_cached_worker_audit

BASE=pathlib.Path(__file__).resolve().parents[1]


def fixture(period=3):
    retained={0:360,2:540,3:480}[period]
    row=test_cached_worker_audit.CachedWorkerAuditTests().fixture(kind='rate',fps=60,measured=retained/12)
    row.update(compat_probe_requested=True,compat_keep_every=period)
    row['probe']['worker_status'].update(cached_compat_probe=True,nonref_probe_active=True,
        nonref_keep_every=period,encoded_nonref_skipped=720-retained,high_fps_compat=True)
    row['probe']['rate'].update(encoded_annexb=720,encoded_disposable=360,encoded_reference=360,
        encoded_nonref_skipped=720-retained,encoded_invalid=0,encoded_unsupported=0,position_advance=12,consumed_frames=retained)
    return assess(row,'cached','rate',compat_keep=period)


class CachedCompatTests(unittest.TestCase):
    def test_three_policies_are_not_full_rate_passes(self):
        for period,fps in ((0,30),(3,40),(2,45)):
            row=fixture(period)
            self.assertTrue(row['passed']);self.assertTrue(row['compatibility_rate_met'])
            self.assertFalse(row['worker_rate_met']);self.assertFalse(row['playback_passed'])
            result=audit_row(row,compat=True)['compatibility']
            self.assertEqual(result['estimated_retained_fps'],fps)
            self.assertFalse(result['full_source_rate_passed'])
            self.assertTrue(inspect_result(row)['current_observation_gate_passed'])

    def test_existing_full_source_audit_refuses_compatibility_rows(self):
        row=fixture()
        self.assertFalse(assess(copy.deepcopy(row),'cached','rate')['passed'])
        with self.assertRaises(ValueError):audit_row(row)

    def test_lateness_does_not_become_a_compatibility_pass(self):
        for change in (lambda r:r.update(drops=8),lambda r:r.update(decoder_drops=8),
                       lambda r:r.update(position_advance=10),
                       lambda r:r.update(consumed_frames=400,consumed_fps=400/12),
                       lambda r:r.update(encoded_invalid=1),
                       lambda r:r.update(encoded_nonref_skipped=300)):
            rate=fixture()['probe']['rate'];change(rate)
            self.assertFalse(evaluate(rate,3,True)['compatibility_rate_met'])

    def test_metadata_and_sync_mode_must_match(self):
        for change in (lambda r:r.update(compat_probe_requested=False),
                       lambda r:r['probe']['worker_status'].update(cached_compat_probe=False),
                       lambda r:r['probe']['worker_status'].update(nonref_probe_active=False),
                       lambda r:r['probe']['worker_status'].update(nonref_keep_every=0),
                       lambda r:r['probe']['worker_status'].update(unsynchronized_throughput_probe=True)):
            row=fixture();change(row)
            self.assertFalse(assess(row,'cached','rate',compat_keep=3)['passed'])
        self.assertFalse(assess(fixture(),'cached','throughput',compat_keep=3)['passed'])
        self.assertFalse(assess(fixture(),'uncached','rate',compat_keep=3)['passed'])

    def test_incomplete_failed_run_is_preserved(self):
        row=fixture();row['probe'].pop('rate');row['child_exit']=1
        result=assess(row,'cached','rate',compat_keep=3)
        self.assertFalse(result['passed']);self.assertFalse(result['compatibility_evidence_valid'])
        self.assertEqual(result['child_exit'],1)

    def test_numeric_bounds_and_arithmetic(self):
        for change in (lambda r:r.update(encoded_nonref_skipped=1000),lambda r:r.update(encoded_reference=700),
                       lambda r:r.update(consumed_fps=44),lambda r:r.update(source_fps=30),
                       lambda r:r.update(elapsed_seconds=float('nan')),lambda r:r.update(encoded_disposable=True)):
            rate=fixture()['probe']['rate'];change(rate)
            with self.assertRaises(ValueError):evaluate(rate,3,True)
        with self.assertRaises(ValueError):evaluate(fixture()['probe']['rate'],1,True)

    def test_only_private_generated_source_changes(self):
        spec=importlib.util.spec_from_file_location('compat_overlay',BASE/'build/cached_compat_overlay.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        original=(BASE/'client/hardware_worker.cpp').read_text(encoding='utf-8');result=module.overlay(original)
        self.assertIn('!p011_hw::valid_cached_compat(',result)
        self.assertIn('w!=1920||h!=1080',result)
        self.assertIn('!request.value("muted",false)||limit>40',result)
        self.assertEqual(original.count('if(throughput_probe&&'),result.count('if(throughput_probe&&'))
        self.assertIn('request.value("nonref_probe",false)||request.value("high_fps_compat",false)))return 41;',result)
        self.assertNotIn('cached_compat_probe',original)
        self.assertNotIn('cached_compat',(BASE/'build/build_hardware.py').read_text())
        with self.assertRaises(ValueError):module.overlay(result)

    def test_private_driver_uses_matching_launch_guard(self):
        spec=importlib.util.spec_from_file_location('compat_overlay',BASE/'build/cached_compat_overlay.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        original=(BASE/'client/hardware_client.hpp').read_text(encoding='utf-8')
        result=module.client_overlay(original)
        self.assertIn('!p011_hw::valid_cached_compat(',result)
        for guard in ('!request.value("private_omx_probe",false)',
                      '!request.value("fused_half_probe",false)',
                      '!request.value("muted",false)',
                      'request.value("limit",0)>40', 'request.value("limit",0)<10',
                      'request.value("width",0)!=1920', 'request.value("height",0)!=1080',
                      'request.value("ion_observe",false)'):
            self.assertIn(guard,result)
        # No changes to the actual shared source or non-diagnostic branches.
        old_cache=original.index('#ifdef P011_OUTPUT_CACHE_PROBE\n        const std::string cache_mode')
        new_cache=result.index('#ifdef P011_OUTPUT_CACHE_PROBE\n        const std::string cache_mode')
        old_end=original.index('#endif',old_cache);new_end=result.index('#endif',new_cache)
        self.assertEqual(original[old_end:],result[new_end:])
        self.assertNotIn('cached_compat_probe',original)
        with self.assertRaises(ValueError):module.client_overlay(result)
        driver=(BASE/'probes/hardware_seek_probe.cpp').read_text(encoding='utf-8')
        generated=module.probe_overlay(driver)
        self.assertIn('#include "hardware_client.hpp"',generated)
        self.assertNotIn('#include "../client/hardware_client.hpp"',generated)
        with self.assertRaises(ValueError):module.probe_overlay(generated)
        recipe=(BASE/'build/build_cached_worker.py').read_text(encoding='utf-8')
        self.assertIn("format_work/'hardware_seek_probe.cpp'",recipe)
        self.assertIn("str(format_work/'hardware_client.hpp') not in dependencies",recipe)
        self.assertIn("'/src/client/hardware_client.hpp' in dependencies",recipe)

    def test_python35_and_cli_rejects_unsynchronized_or_wrong_quality(self):
        source=payload();ast.parse(source,feature_version=(3,5))
        self.assertIn("if THROUGHPUT or CACHE_MODE!='cached'",source)
        self.assertIn("init['cached_compat_probe']=COMPAT",source)
        for kind,quality in (('throughput','116'),('rate','80')):
            proc=subprocess.run([sys.executable,str(BASE/'host/cached_seek_trial.py'),'--artifact','missing',
                '--bundle','missing','--mode','cached','--kind',kind,'--quality',quality,'--compat-keep','3'],
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
            self.assertEqual(proc.returncode,2)
            self.assertIn(b'Compatibility needs cached q116',proc.stderr)


if __name__=='__main__':unittest.main()
