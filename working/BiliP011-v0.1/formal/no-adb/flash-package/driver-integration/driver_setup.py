"""Pinned VCOM driver preinstallation. No USB protocol or flashing capability."""
import argparse
import ctypes
from ctypes import wintypes as wt
import hashlib
import json
import pathlib
import platform
import subprocess
import sys
import time

from flash import ROOT, verify_package

FILES = {
    'sprdvcom.inf': '7aa924930285803b50f4468f071657da11c4764b4364d4cca43757e766cd6987',
    'sprdvcom.cat': 'bd421e4efffd1629a3efd8b7112f7aba675ad36b8816ebcac6c947a7cfeab9ff',
    'amd64/sprdvcom.sys': '53e573cd4d5371ede7846f0f6e5243367e24b18e1d374dd999c052302c65e182',
    'amd64/WdfCoInstaller01009.dll': '4cf39fae9f8e3a2ed6f479ab24dd669b0fcdd28879e70785afa3d5f13c12f3ae',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def check_host():
    if sys.platform != 'win32' or ctypes.sizeof(ctypes.c_void_p) != 8 or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise RuntimeError('本驱动包仅支持 Windows x64，不支持 ARM64 或 32 位系统。')
    version = sys.getwindowsversion()
    if version.major < 10 or version.build < 14393:
        raise RuntimeError('需要 Windows 10 1607 或更新版本。')


def system_directory():
    api = ctypes.WinDLL('kernel32', use_last_error=True).GetSystemDirectoryW
    api.argtypes = [wt.LPWSTR, wt.UINT]
    api.restype = wt.UINT
    buf = ctypes.create_unicode_buffer(32768)
    size = api(buf, len(buf))
    if not size or size >= len(buf):
        raise ctypes.WinError(ctypes.get_last_error())
    return pathlib.Path(buf.value)


def verify_driver_bundle():
    folder = ROOT / 'drivers/UNISOC-VCOM-4.20.42.134'
    for name, expected in FILES.items():
        path = folder / name
        if path.is_symlink() or not path.is_file() or digest(path) != expected:
            raise RuntimeError('驱动文件缺失或校验失败：' + name)
    return folder


def registered_driver():
    """Require all signed bytes AND an actual published OEM INF, no elevation."""
    repository = system_directory() / 'DriverStore/FileRepository'
    api = ctypes.WinDLL('setupapi', use_last_error=True).SetupGetInfPublishedNameW
    api.argtypes = [wt.LPCWSTR, wt.LPWSTR, wt.DWORD, ctypes.POINTER(wt.DWORD)]
    api.restype = wt.BOOL
    for folder in sorted(repository.glob('sprdvcom.inf_amd64_*')):
        try:
            if any(not (folder / name).is_file() or digest(folder / name) != expected for name, expected in FILES.items()):
                continue
            buf = ctypes.create_unicode_buffer(32768)
            needed = wt.DWORD()
            if not api(str(folder / 'sprdvcom.inf'), buf, len(buf), ctypes.byref(needed)):
                continue
            published = pathlib.Path(buf.value)
            # Some Windows builds return only oemNNN.inf despite the documented
            # fully qualified return. Resolve this strictly in the Windows INF dir.
            if not published.is_absolute():
                if len(published.parts) != 1 or not published.name.lower().startswith('oem') or published.suffix.lower() != '.inf':
                    continue
                published = system_directory().parent / 'INF' / published
            if published.is_file() and digest(published) == FILES['sprdvcom.inf']:
                return {'store': str(folder), 'published_inf': str(published), 'version': '4.20.42.134'}
        except OSError:
            continue
    return None


def is_admin():
    api = ctypes.WinDLL('shell32', use_last_error=True).IsUserAnAdmin
    api.argtypes = []
    api.restype = wt.BOOL
    return bool(api())


def install_driver(output):
    """Admin helper only stages this one INF. Never updates a connected device."""
    check_host()
    verify_package()
    folder = verify_driver_bundle()
    if not is_admin():
        raise RuntimeError('驱动安装需要 Windows 管理员授权。')
    command = [str(system_directory() / 'pnputil.exe'), '/add-driver', str(folder / 'sprdvcom.inf')]
    save(output / 'pnputil.command.json', command)
    with (output / 'pnputil.stdout.raw').open('xb') as stdout, (output / 'pnputil.stderr.raw').open('xb') as stderr:
        try:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                    timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 124
    found = registered_driver() if code == 0 else None
    save(output / 'driver-helper-result.json', {'pnputil_exit': code, 'registered': found,
        'reboot_requested': code in (3010, 1641), 'usb_protocol_used': False,
        'command_scope': 'stage_single_signed_inf_no_install_no_reboot'})
    return code if code else (0 if found else 1)


def elevate_helper(output):
    class ShellInfo(ctypes.Structure):
        _fields_ = [('cbSize', wt.DWORD), ('fMask', wt.ULONG), ('hwnd', wt.HWND),
            ('lpVerb', wt.LPCWSTR), ('lpFile', wt.LPCWSTR), ('lpParameters', wt.LPCWSTR),
            ('lpDirectory', wt.LPCWSTR), ('nShow', ctypes.c_int), ('hInstApp', wt.HINSTANCE),
            ('lpIDList', ctypes.c_void_p), ('lpClass', wt.LPCWSTR), ('hkeyClass', wt.HKEY),
            ('dwHotKey', wt.DWORD), ('hIconOrMonitor', wt.HANDLE), ('hProcess', wt.HANDLE)]
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    ole = ctypes.WinDLL('ole32', use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellInfo)]
    shell.ShellExecuteExW.restype = wt.BOOL
    kernel.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    kernel.WaitForSingleObject.restype = wt.DWORD
    kernel.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
    kernel.GetExitCodeProcess.restype = wt.BOOL
    kernel.CloseHandle.argtypes = [wt.HANDLE]
    kernel.CloseHandle.restype = wt.BOOL
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, wt.DWORD]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    initialized = ole.CoInitializeEx(None, 0x2 | 0x4) in (0, 1)
    info = ShellInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40 | 0x100  # NOCLOSEPROCESS | NOASYNC
    info.lpVerb = 'runas'
    info.lpFile = sys.executable
    args = ['-B', '-X', 'utf8', str(ROOT / 'app/driver_setup.py'), '--elevated', '--output', str(output)]
    info.lpParameters = subprocess.list2cmdline(args)
    info.lpDirectory = str(ROOT)
    info.nShow = 0
    save(output / 'elevated.command.json', [sys.executable] + args)
    try:
        if not shell.ShellExecuteExW(ctypes.byref(info)):
            return ctypes.get_last_error() or 1
        if not info.hProcess:
            return 1
        deadline = time.monotonic() + 240
        while True:
            wait = kernel.WaitForSingleObject(info.hProcess, 250)
            if wait == 0:
                code = wt.DWORD()
                if not kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(code)):
                    raise ctypes.WinError(ctypes.get_last_error())
                return code.value
            if wait != 258:
                raise ctypes.WinError(ctypes.get_last_error())
            if time.monotonic() >= deadline:
                # Do not kill an in-progress system driver transaction or start flashing.
                return 124
    finally:
        if info.hProcess:
            kernel.CloseHandle(info.hProcess)
        if initialized:
            ole.CoUninitialize()


def ensure_driver(output):
    check_host()
    verify_driver_bundle()
    output.mkdir(exist_ok=False)
    found = registered_driver()
    if found:
        save(output / 'driver-result.json', {'status': 'READY_ALREADY_REGISTERED', 'registered': found, 'install_attempted': False})
        print('已核对本机已注册的 UNISOC 下载串口驱动，跳过重复安装。', flush=True)
        return 0
    print('正在准备内置 UNISOC 下载串口驱动。若出现 Windows 管理员授权提示，请允许；此步只安装电脑驱动。', flush=True)
    code = install_driver(output) if is_admin() else elevate_helper(output)
    found = registered_driver() if code == 0 else None
    state = 'READY_REGISTERED' if code == 0 and found else 'DRIVER_NOT_READY'
    save(output / 'driver-result.json', {'status': state, 'helper_exit': code, 'registered': found, 'install_attempted': True})
    if code in (3010, 1641):
        print('驱动安装要求重启电脑。本次已停止，请正常重启 Windows 后重新运行；未开始刷写。')
        return code
    if code == 1223:
        print('已取消 Windows 管理员授权，未开始刷写。')
        return code
    if code or not found:
        print('驱动尚未就绪，未开始刷写。请保留日志；不会关闭签名验证或强制换驱动。')
        return code or 1
    print('内置下载驱动已注册，插入设备时由 Windows 正常匹配。', flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--elevated', action='store_true', required=True)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / 'logs').resolve()) or not output.is_dir():
        raise RuntimeError('驱动日志目录不属于当前安装包。')
    try:
        return install_driver(output)
    except Exception as exc:
        save(output / 'driver-helper-error.json', {'type': type(exc).__name__, 'message': str(exc)})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
