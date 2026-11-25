"""Offline ARM/QRC inspection of the exact v2.4.0 backup, never executes it."""
import hashlib
import io
import pathlib
import struct
import sys
BASE=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'.hostdeps'))
from elftools.elf.elffile import ELFFile
from capstone import Cs,CS_ARCH_ARM,CS_MODE_ARM,CS_MODE_THUMB
path=BASE.parents[1]/'06_Firmware/backups/v2.4.0-20260923-162730/files/Z03'
raw=path.read_bytes()
assert hashlib.sha256(raw).hexdigest()=='cb8d6a78617d50f64c6adc8056427dd963bc83979cbb04e349275dd8e8ffb62a'
elf=ELFFile(io.BytesIO(raw));dyn=elf.get_section_by_name('.dynsym')
for name in ('.text','.rodata','.plt','.rel.plt','.init_array'):
 sec=elf.get_section_by_name(name);print(name,hex(sec['sh_addr']),hex(sec['sh_offset']),sec['sh_size'])
plt=elf.get_section_by_name('.plt');rel=elf.get_section_by_name('.rel.plt')
for i,row in enumerate(rel.iter_relocations()):
 sym=dyn.get_symbol(row['r_info_sym'])
 if 'qRegisterResourceData' in sym.name:
  address=plt['sh_addr']+20+12*i
  print('REGISTER',i,hex(row['r_offset']),hex(address),sym.name)
  decoder=Cs(CS_ARCH_ARM,CS_MODE_ARM)
  for ins in decoder.disasm(plt.data()[20+12*i:20+12*i+12],address):print(hex(ins.address),ins.mnemonic,ins.op_str)
  text=elf.get_section_by_name('.text')
  for mode in (CS_MODE_ARM,CS_MODE_THUMB):
   decoder=Cs(CS_ARCH_ARM,mode);decoder.skipdata=True
   for ins in decoder.disasm(text.data(),text['sh_addr']):
    if ins.mnemonic in ('bl','blx','b') and ins.op_str in ('#'+hex(address),'#'+hex(address+1)):
     print('CALL',mode,hex(ins.address))
     offset=ins.address-text['sh_addr'];start=max(0,offset-48)
     for item in decoder.disasm(text.data()[start:offset+80],text['sh_addr']+start):print(hex(item.address),item.mnemonic,item.op_str)
  break
