"""Offline inspection of the already backed-up stock kernel; never accesses ADB.

Only selected kernel diagnostic text / code references are reported. Firmware
and decompressed kernel remain local, and no executable is run from the image.
"""
import datetime
import hashlib
import json
import pathlib
import struct
import sys
import zlib

BASE = pathlib.Path(__file__).resolve().parents[1]
ROOT = BASE.parents[1]
BOOT = ROOT / '06_Firmware/backups/v2.4.0-20260923-162730/p27-boot.img'


def inspect(blob):
    markers = [b'ion_new_alloc dumb buffer fail', b'failed to allocate buffer with size %llu,use ion']
    streams = []
    start = 0
    while len(streams) < 32:
        start = blob.find(b'\x1f\x8b\x08', start)
        if start < 0:
            break
        try:
            decoder = zlib.decompressobj(31)
            kernel = decoder.decompress(blob[start:], 32 * 1024 * 1024 + 1)
            if decoder.eof and len(kernel) <= 32 * 1024 * 1024 and b'Linux version ' in kernel:
                streams.append((start, kernel))
        except zlib.error:
            pass
        start += 3
    if len(streams) != 1:
        raise ValueError('Expected exactly one bounded gzip kernel stream; got ' + str(len(streams)))
    offset, kernel = streams[0]
    at = kernel.index(b'Linux version ')
    version = kernel[at:kernel.find(b'\0', at)].decode('ascii', 'replace')
    rows = []
    for marker in markers:
        at = kernel.find(marker)
        row = {'marker': marker.decode(), 'found': at >= 0, 'references': []}
        if at >= 0:
            row['string_offset'] = at
            # ARM32 Linux uncompressed Image starts at PAGE_OFFSET + 0x8000.
            # Keep each candidate explicitly labelled; this is not a symbol map.
            for base in (0xc0008000, 0x80008000):
                address = base + at
                # DRM macros commonly embed the message in a longer prefix.
                text_start = kernel.rfind(b'\0', max(0, at - 256), at) + 1
                for string_at in sorted(set((at, text_start))):
                    needle = struct.pack('<I', base + string_at)
                    cursor = 0
                    while True:
                        ref = kernel.find(needle, cursor)
                        if ref < 0:
                            break
                        if ref % 4 == 0:
                            row['references'].append({'image_base_assumption': hex(base), 'literal_offset': ref,
                                                      'string_offset': string_at})
                        cursor = ref + 4
        rows.append(row)
    return kernel, {'gzip_offset': offset, 'kernel_bytes': len(kernel),
                    'kernel_sha256': hashlib.sha256(kernel).hexdigest(), 'version': version,
                    'markers': rows, 'device_accessed': False, 'firmware_written': False}


def main():
    blob = BOOT.read_bytes()
    kernel, report = inspect(blob)
    report['boot_sha256'] = hashlib.sha256(blob).hexdigest()
    # Existing project dependency; no new package installation or remote code.
    deps = ROOT / 'working/diagnosis-20260923-bt-fix/deps'
    sys.path.insert(0, str(deps))
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
    disasm = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    excerpts = []
    report['fallback_call_candidates'] = []
    for item in report['markers']:
        for ref in item['references']:
            at = ref['literal_offset']
            if at > len(kernel) or at < 512:
                continue
            base = int(ref['image_base_assumption'], 16)
            excerpts.append('MARKER=' + item['marker'] + '\nASSUMPTION=' + ref['image_base_assumption'])
            instructions = list(disasm.disasm(kernel[at-384:at+32], base+at-384))
            for i,instruction in enumerate(instructions):
                excerpts.append('%08x: %s %s' % (instruction.address, instruction.mnemonic, instruction.op_str))
                # Identify the exact argument setup preceding the allocator
                # call; retain the image-base assumption and numeric offsets.
                if i+3<len(instructions) and [(v.mnemonic,v.op_str) for v in instructions[i:i+3]]==[
                        ('mov','r2, #0'),('mov','r1, #8'),('ldr','r0, [r5, #0x18]')] and instructions[i+3].mnemonic=='bl':
                    call=instructions[i+3]
                    candidate={'image_base_assumption':hex(base),'call_offset':call.address-base,
                               'heap_mask':8,'selected_heap_id':3,'flags':0,
                               'target_offset':int(call.op_str.lstrip('#'),16)-base}
                    if candidate not in report['fallback_call_candidates']:
                        report['fallback_call_candidates'].append(candidate)
    for candidate in report['fallback_call_candidates']:
        at=candidate['target_offset'];base=int(candidate['image_base_assumption'],16)
        excerpts.append('ALLOCATOR_CALLEE='+hex(base+at))
        for instruction in disasm.disasm(kernel[at:at+400],base+at):
            excerpts.append('%08x: %s %s' % (instruction.address,instruction.mnemonic,instruction.op_str))
    out = ROOT / 'logs' / ('BiliP011-KernelOffline-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir()
    (out / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    (out / 'code-references.txt').write_text('\n'.join(excerpts), encoding='utf-8')
    print(json.dumps(report, indent=2))
    print('LOG_DIR=' + str(out))
    print('\n'.join(excerpts))


if __name__ == '__main__':
    main()
