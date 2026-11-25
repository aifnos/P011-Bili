"""PC-only narrow ARM ELF constant references; no device access or mutation."""
import argparse,io,pathlib,re,struct,sys
ROOT=pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'working/diagnosis-20260923-bt-fix/deps'))
from elftools.elf.elffile import ELFFile
from capstone import Cs,CS_ARCH_ARM,CS_MODE_ARM

def main():
    p=argparse.ArgumentParser();p.add_argument('file',type=pathlib.Path);p.add_argument('value',type=lambda s:int(s,0));a=p.parse_args()
    blob=a.file.read_bytes();elf=ELFFile(io.BytesIO(blob));sec=elf.get_section_by_name('.text');code=sec.data();base=sec['sh_addr']
    segments=[s for s in elf.iter_segments() if s['p_type']=='PT_LOAD']
    def word(address):
        for s in segments:
            if s['p_vaddr']<=address and address+4<=s['p_vaddr']+s['p_filesz']:
                return struct.unpack_from('<I',blob,address-s['p_vaddr']+s['p_offset'])[0]
        return None
    cs=Cs(CS_ARCH_ARM,CS_MODE_ARM);cs.skipdata=True;regs={};hits=[]
    for at,size,mnemonic,op in cs.disasm_lite(code,base):
        match=re.fullmatch(r'(\w+), #(0x[0-9a-f]+|[0-9]+)',op)
        if match and mnemonic in ('mov','movw'):regs[match[1]]=int(match[2],0)
        elif match and mnemonic=='movt' and match[1] in regs:
            regs[match[1]]=(regs[match[1]]&65535)|(int(match[2],0)<<16)
        load=re.fullmatch(r'(\w+), \[pc(?:, #(-?(?:0x[0-9a-f]+|[0-9]+)))?\]',op)
        if mnemonic=='ldr' and load:
            v=word(at+8+int(load[2] or '0',0))
            if v is not None:regs[load[1]]=v
        add=re.fullmatch(r'(\w+), (\w+), (\w+|#(?:0x[0-9a-f]+|[0-9]+))',op)
        if mnemonic=='add' and add:
            lhs=at+8 if add[2]=='pc' else regs.get(add[2]);rhs=int(add[3][1:],0) if add[3].startswith('#') else regs.get(add[3])
            if lhs is not None and rhs is not None:regs[add[1]]=(lhs+rhs)&0xffffffff
        if any(v==a.value for v in regs.values()) and (not hits or at-hits[-1]>256):hits.append(at)
        if mnemonic=='bl':
            for r in ('r0','r1','r2','r3'):regs.pop(r,None)
    imports={};rel=elf.get_section_by_name('.rel.plt');syms=elf.get_section(rel['sh_link']);plt=elf.get_section_by_name('.plt')
    for i,r in enumerate(rel.iter_relocations()):imports[plt['sh_addr']+20+12*i]=syms.get_symbol(r['r_info_sym']).name
    for hit in hits:
        print('REFERENCE',hex(hit))
        start=max(base,hit-64);part=code[start-base:hit-base+192]
        for at,size,mn,op in cs.disasm_lite(part,start):
            target=int(op[1:],0) if mn.startswith('bl') and op.startswith('#') else None
            print('%08x %-8s %-35s %s'%(at,mn,op,imports.get(target,'')))

if __name__=='__main__':main()
