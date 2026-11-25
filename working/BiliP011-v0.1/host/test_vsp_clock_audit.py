import ast,inspect,struct,unittest
from vsp_clock_audit import decode_properties,PROBE


class ClockTreeTests(unittest.TestCase):
    def sample(self):
        return {'compatible':b'sprd,sharkle-vsp\0','clock-names':b'clk_src_76m8\0clk_src_307m2\0',
                'clocks':struct.pack('>IIII',123,4,123,5)}

    def test_labels_are_not_measured_frequencies(self):
        result=decode_properties(self.sample())
        self.assertEqual(result['raw_clock_cells'],[123,4,123,5])
        self.assertEqual(result['source_names'],['clk_src_76m8','clk_src_307m2'])
        self.assertFalse(result['actual_clock_measured']);self.assertFalse(result['clock_specifiers_decoded'])
        self.assertFalse(result['frequency_changed'])

    def test_rejects_unexpected_or_unbounded_properties(self):
        for field,value in (('serial-number',b'private'),('clock-names',b'secret://private\0'),
                            ('clock-names',b'a'*1025),('compatible',b'unterminated'),('clocks',b'x')):
            properties=self.sample();properties[field]=value
            with self.assertRaises(ValueError):decode_properties(properties)

    def test_target_is_python35_and_read_only(self):
        source=inspect.getsource(decode_properties)+'\n'+PROBE
        ast.parse(source,feature_version=(3,5))
        for forbidden in ('ioctl(', 'subprocess.', 'os.system(', 'os.unlink(', "'wb'", 'mount(', '/dev/mem'):
            self.assertNotIn(forbidden,source)
        self.assertIn('require_private_idle()',PROBE)
        self.assertIn("('compatible','clock-names','clocks')",PROBE)


if __name__=='__main__':unittest.main()
