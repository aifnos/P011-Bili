"""PC-only whitelist policy: one private plugin path, not arbitrary nesting."""
import ast,pathlib,unittest

class PluginPathTests(unittest.TestCase):
    def test_only_exact_plugin_path_expands_flat_media_allowlist(self):
        source=(pathlib.Path(__file__).resolve().parents[1]/'host/build_awake_trial.py').read_text()
        tree=ast.parse(source)
        node=next(n for n in ast.walk(tree) if isinstance(n,ast.If) and any(isinstance(x,ast.Constant) and x.value=='Unsafe media path' for x in ast.walk(n)))
        expression=compile(ast.Expression(node.test),'<media whitelist>','eval')
        import re
        for name in ('lib/gst/libgstomx.so','lib/libmpv.so.2','bin/bili-hw'):
            self.assertFalse(eval(expression,{'re':re,'name':name}))
        for name in ('lib/gst/../libgstomx.so','lib/gst/other.so','lib/../../usr/bin/Z03','/usr/lib/libgstomx.so','lib\\gst\\libgstomx.so'):
            self.assertTrue(eval(expression,{'re':re,'name':name}))

if __name__=='__main__':unittest.main()
