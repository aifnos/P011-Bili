"""Invoke the existing Qt 5.10 Quick Test entry for an isolated finite UI trial.

No private Qt ABI objects, new Qt libraries, original UI hooks, or system writes.
The function signature follows qt/qtdeclarative v5.10.1 quicktest.h. This is a
development/test launcher, not a replacement vendor boot program.
"""
import argparse
import ctypes
import os
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input')
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    # The target omits the resource module. Linux RLIMIT_CORE is 4 on this
    # verified ARM ABI; disable core output for this child only via libc.
    class Limit(ctypes.Structure):
        _fields_=[('soft',ctypes.c_ulong),('hard',ctypes.c_ulong)]
    libc=ctypes.CDLL(None,use_errno=True)
    libc.setrlimit.argtypes=[ctypes.c_int,ctypes.POINTER(Limit)]
    libc.setrlimit.restype=ctypes.c_int
    if libc.setrlimit(4,ctypes.byref(Limit(0,0)))!=0:
        raise OSError(ctypes.get_errno(),'Cannot disable child core output')
    library=ctypes.CDLL('/usr/lib/libQt5QuickTest.so.5',mode=ctypes.RTLD_GLOBAL)
    entry=getattr(library,'_Z15quick_test_mainiPPcPKcS2_')
    entry.restype=ctypes.c_int
    entry.argtypes=[ctypes.c_int,ctypes.POINTER(ctypes.c_char_p),ctypes.c_char_p,ctypes.c_char_p]
    if args.check:
        print('QT_QUICKTEST_NATIVE_ENTRY=AVAILABLE',flush=True);return 0
    if not args.input or not os.path.isfile(args.input):raise ValueError('Explicit QML trial input required')
    values=[b'p011-native-trial',b'-platform',b'wayland',b'-input',os.fsencode(args.input)]
    argv=(ctypes.c_char_p*(len(values)+1))(*(values+[None]))
    return entry(len(values),argv,b'P011NativeTrial',None)


if __name__=='__main__':sys.exit(main())
