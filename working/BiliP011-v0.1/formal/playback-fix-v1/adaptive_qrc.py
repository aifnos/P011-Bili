"""Locate Qt ARM resource registration and patch only the feedback record."""
import hashlib
import io
import re
import struct
import zlib

RESOURCE='/ZybQmlFiles/ZybSet/SetUserReport.qml'
SET_MAIN='/ZybQmlFiles/ZybSet/SetMainPage.qml'
LOGIC='/ZybQmlFiles/Funcs/UILogics.js'


def sha(data):return hashlib.sha256(data).hexdigest()


def registrations(raw):
    from elftools.elf.elffile import ELFFile
    from capstone import Cs,CS_ARCH_ARM,CS_MODE_ARM
    from capstone.arm import ARM_OP_IMM,ARM_OP_REG,ARM_OP_MEM
    if raw[:6]!=b'\x7fELF\x01\x01' or struct.unpack_from('<H',raw,18)[0]!=40:
        raise ValueError('Target Z03 must be ELF32 ARM little endian')
    elf=ELFFile(io.BytesIO(raw))
    text=elf.get_section_by_name('.text');plt=elf.get_section_by_name('.plt')
    rel=elf.get_section_by_name('.rel.plt');dyn=elf.get_section_by_name('.dynsym')
    if any(x is None for x in (text,plt,rel,dyn)):raise ValueError('ELF resource registration sections missing')
    def offset(va):
        for segment in elf.iter_segments():
            if segment['p_type']=='PT_LOAD' and segment['p_vaddr']<=va<segment['p_vaddr']+segment['p_filesz']:
                return segment['p_offset']+va-segment['p_vaddr']
        raise ValueError('Resource pointer outside ELF file')
    targets=set()
    for i,row in enumerate(rel.iter_relocations()):
        if 'qRegisterResourceData' in dyn.get_symbol(row['r_info_sym']).name:
            targets.add(plt['sh_addr']+20+12*i)
    if not targets:raise ValueError('Qt resource registration function missing')
    decoder=Cs(CS_ARCH_ARM,CS_MODE_ARM);decoder.detail=True;decoder.skipdata=True
    data=text.data();base=text['sh_addr'];found=[]
    for ins in decoder.disasm(data,base):
        if ins.mnemonic not in ('b','bl','blx') or not ins.operands or ins.operands[0].type!=ARM_OP_IMM:
            continue
        if ins.operands[0].imm not in targets:continue
        start=max(0,ins.address-base-80);start-=start%4
        regs={}
        for item in decoder.disasm(data[start:ins.address-base],base+start):
            ops=item.operands
            if item.mnemonic in ('bl','blx'):regs={};continue
            if not ops or ops[0].type!=ARM_OP_REG:continue
            rd=item.reg_name(ops[0].reg)
            if rd not in ('r0','r1','r2','r3'):continue
            value=None
            def operand(op):
                if op.type==ARM_OP_IMM:return op.imm
                if op.type==ARM_OP_REG:
                    name=item.reg_name(op.reg)
                    return item.address+8 if name=='pc' else regs.get(name)
                return None
            if item.mnemonic=='mov' and len(ops)==2:value=operand(ops[1])
            elif item.mnemonic in ('add','sub') and len(ops)==3:
                a,b=operand(ops[1]),operand(ops[2])
                if a is not None and b is not None:value=a+b if item.mnemonic=='add' else a-b
            elif item.mnemonic=='ldr' and len(ops)==2 and ops[1].type==ARM_OP_MEM and item.reg_name(ops[1].mem.base)=='pc':
                at=offset(item.address+8+ops[1].mem.disp)
                value=struct.unpack_from('<I',raw,at)[0]
            regs[rd]=None if value is None else value&0xffffffff
        if regs.get('r0') not in (1,2) or any(regs.get('r'+str(i)) is None for i in (1,2,3)):continue
        try:record=(regs['r0'],offset(regs['r1']),offset(regs['r2']),offset(regs['r3']))
        except ValueError:continue
        if record not in found:found.append(record)
    return found


def resource_map(raw,registration):
    version,tree,names,data=registration
    node_bytes=22 if version==2 else 14
    seen=set();rows={};expanded=0
    def walk(index,parent):
        nonlocal expanded
        if index in seen or index<0 or index>=4096:raise ValueError('Invalid resource tree index')
        seen.add(index);at=tree+index*node_bytes
        if at<0 or at+node_bytes>len(raw):raise ValueError('Resource tree outside file')
        no,flags=struct.unpack_from('>IH',raw,at)
        if flags not in (0,1,2):raise ValueError('Unknown resource flags')
        pos=names+no
        if pos<0 or pos+6>len(raw):raise ValueError('Invalid resource name offset')
        count=struct.unpack_from('>H',raw,pos)[0]
        if count>512 or pos+6+count*2>len(raw):raise ValueError('Invalid resource name length')
        name=raw[pos+6:pos+6+count*2].decode('utf-16-be')
        if '/' in name or '\x00' in name:raise ValueError('Invalid resource component')
        path=parent+'/'+name if index else ''
        if flags&2:
            count,first=struct.unpack_from('>II',raw,at+6)
            if count>4096:raise ValueError('Resource child bound exceeded')
            for child in range(first,first+count):walk(child,path)
        else:
            offset=data+struct.unpack_from('>I',raw,at+10)[0]
            if offset<0 or offset+4>len(raw):raise ValueError('Resource data offset outside file')
            size=struct.unpack_from('>I',raw,offset)[0]
            if size>16*1024*1024 or offset+4+size>len(raw):raise ValueError('Resource size bound exceeded')
            body=raw[offset+4:offset+4+size]
            if flags&1:
                if len(body)<4:raise ValueError('Truncated compressed resource')
                expected=struct.unpack_from('>I',body)[0]
                if expected>16*1024*1024:raise ValueError('Expanded resource bound exceeded')
                dec=zlib.decompressobj();body=dec.decompress(body[4:],expected+1)
                if not dec.eof or dec.unused_data or dec.unconsumed_tail or len(body)!=expected:
                    raise ValueError('Compressed resource invalid')
            expanded+=len(body)
            if expanded>64*1024*1024 or path in rows:raise ValueError('Resource collection bound or uniqueness failed')
            rows[path]=dict(offset=offset,size=size,flags=flags,body=body)
    walk(0,'')
    return rows


def wrapper(rid):
    if not re.fullmatch('[a-f0-9]{24}',rid):raise ValueError('Invalid release ID')
    return ('''import QtQuick 2.7
import "qrc:/ZybQmlFiles/Funcs/UILogics.js" as UILogic
Rectangle {
anchors.fill:parent; color:"#16171b"
Loader { id:content; anchors.fill:parent; source:"file:///mnt/data/p011-toolbox/bili-formal/releases/%s/app/FeedbackEntry.qml" }
Text { anchors.centerIn:parent; text:"B 站程序暂不可用，请返回设置"; color:"white"; visible:content.status===Loader.Error }
MouseArea { x:0;y:0;width:140;height:56;visible:content.status===Loader.Error;onClicked:UILogic.backToSetPage() }
}
'''%rid).encode('utf8')


def patch_feedback(raw,rid):
    matches=[]
    for registration in registrations(raw):
        try:rows=resource_map(raw,registration)
        except (ValueError,struct.error,UnicodeError,zlib.error):continue
        if all(name in rows for name in (RESOURCE,SET_MAIN,LOGIC)):matches.append((registration,rows))
    if len(matches)!=1:raise ValueError('Expected exactly one Qt collection containing feedback/settings/navigation; found '+str(len(matches)))
    registration,before=matches[0]
    settings=before[SET_MAIN]['body'];logic=before[LOGIC]['body']
    if '用户反馈'.encode('utf8') not in settings or b'SetUserReport.qml' not in settings:
        raise ValueError('Existing user-feedback setting not found')
    if not re.search(rb'function\s+backToSetPage\s*\(',logic):raise ValueError('Existing settings return function missing')
    row=before[RESOURCE];qml=wrapper(rid)
    body=struct.pack('>I',len(qml))+zlib.compress(qml,9) if row['flags']&1 else qml
    if len(body)>row['size']:raise ValueError('Feedback slot too small for fixed entry')
    at,size=row['offset'],row['size']
    block=struct.pack('>I',len(body))+body+bytes(size-len(body))
    candidate=raw[:at]+block+raw[at+4+size:]
    after=resource_map(candidate,registration)
    changed=[name for name in before if before[name]['body']!=after[name]['body']]
    if changed!=[RESOURCE] or after[SET_MAIN]!=before[SET_MAIN] or len(raw)!=len(candidate):
        raise ValueError('Resource boundary verification failed')
    if candidate[:at]!=raw[:at] or candidate[at+4+size:]!=raw[at+4+size:]:
        raise ValueError('Non-feedback executable bytes changed')
    return candidate,dict(registration=list(registration),resources_verified=len(before),
        other_resources_unchanged=len(before)-1,changed_resource=RESOURCE,record_offset=at,
        slot_bytes=size,used_bytes=len(body),original_sha256=sha(raw),patched_sha256=sha(candidate),
        set_main_sha256=sha(settings),outside_resource_record_unchanged=True)
