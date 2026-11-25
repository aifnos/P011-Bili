"""Host-only synthetic config parser checks, not live-kernel evidence."""
import gzip
import unittest
from kernel_observability_audit import decode_config


class KernelObservabilityTests(unittest.TestCase):
    def image(self,raw):return b'prefixIKCFG_ST'+gzip.compress(raw)+b'IKCFG_EDsuffix'
    def test_selected_disabled_flags_and_no_private_configuration(self):
        result=decode_config(self.image(b'CONFIG_IKCONFIG=y\nCONFIG_COMMON_CLK=y\n# CONFIG_DEBUG_FS is not set\n# CONFIG_FTRACE is not set\n# CONFIG_SCHEDSTATS is not set\nCONFIG_LOCALVERSION="PRIVATE"\n'))
        self.assertTrue(result['debug_clock_summary_unavailable']);self.assertTrue(result['ftrace_unavailable'])
        self.assertTrue(result['scheduler_stats_unavailable']);self.assertNotIn('PRIVATE',str(result))
    def test_missing_is_not_disabled(self):
        result=decode_config(self.image(b'CONFIG_COMMON_CLK=y\n'))
        self.assertFalse(result['debug_clock_summary_unavailable']);self.assertFalse(result['ftrace_unavailable'])
        self.assertFalse(result['scheduler_stats_unavailable']);self.assertEqual(result['selected_config']['CONFIG_DEBUG_FS'],'not_recorded')
    def test_enabled_is_not_unavailable(self):
        result=decode_config(self.image(b'CONFIG_DEBUG_FS=y\nCONFIG_FTRACE=y\nCONFIG_SCHEDSTATS=y\n'))
        self.assertFalse(result['debug_clock_summary_unavailable']);self.assertFalse(result['ftrace_unavailable']);self.assertFalse(result['scheduler_stats_unavailable'])
    def test_duplicate_selected_flag_rejected(self):
        with self.assertRaises(ValueError):decode_config(self.image(b'CONFIG_DEBUG_FS=y\n# CONFIG_DEBUG_FS is not set\n'))
    def test_missing_duplicate_reversed_markers_rejected(self):
        for raw in (b'',b'IKCFG_EDIKCFG_ST',self.image(b'x')+b'IKCFG_ST',self.image(b'x')+b'IKCFG_ED'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):decode_config(raw)
    def test_truncated_trailing_and_oversized_stream_rejected(self):
        for raw in (b'IKCFG_ST'+gzip.compress(b'x')[:-3]+b'IKCFG_ED',
                    b'IKCFG_ST'+gzip.compress(b'x')+b'extraIKCFG_ED',self.image(b'x'*(512*1024+1))):
            with self.subTest(size=len(raw)),self.assertRaises(ValueError):decode_config(raw)


if __name__=='__main__':unittest.main()
