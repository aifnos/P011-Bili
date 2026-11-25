"""Read-only/offline v2.4.0 QRC validation and bounded style reference export.

New offsets derived from the ARM call at VA 0x36b2c to qRegisterResourceData(2)
(r1/r2/r3 PC-relative literals at 0x36b40/3c/38), not reused old firmware gates.
Only selected QML is exported as private reference. No font or vendor icon copy.
"""
import hashlib,json,pathlib,struct,zlib
BASE=pathlib.Path(__file__).resolve().parents[1]
SOURCE=BASE.parents[1]/'06_Firmware/backups/v2.4.0-20260923-162730/files/Z03'
raw=SOURCE.read_bytes()
assert hashlib.sha256(raw).hexdigest()=='cb8d6a78617d50f64c6adc8056427dd963bc83979cbb04e349275dd8e8ffb62a'
tree,names,data=[struct.unpack_from('<I',raw,literal-0x10000)[0]+pc-0x10000 for literal,pc in ((0x36b40,0x36b30),(0x36b3c,0x36b2c),(0x36b38,0x36b24))]
assert (tree,names,data)==(0x1a3acc,0x1a5efc,0x1a9f54)
wanted={'/main.qml','/NaviPanel.qml','/ZybQmlFiles/Style/Style.qml','/ZybQmlFiles/ZybSet/SetMainPage.qml','/ZybQmlFiles/ZybControls/ZybText.qml','/ZybQmlFiles/ZybControls/ZybBackButton.qml','/ZybQmlFiles/ZybControls/MToolButton.qml','/ZybQmlFiles/ZybControls/BasicButton.qml'}
seen=set();rows=[];exports={}
def walk(index,parent):
    assert index not in seen and tree+index*22+22<=names;seen.add(index)
    at=tree+22*index;no,flags=struct.unpack_from('>IH',raw,at)
    pos=names+no;length=struct.unpack_from('>H',raw,pos)[0]
    assert names<=pos and pos+6+length*2<=data
    name=raw[pos+6:pos+6+length*2].decode('utf-16-be');path=parent+'/'+name if index else ''
    if flags&2:
        count,first=struct.unpack_from('>II',raw,at+6)
        assert count<1000
        for child in range(first,first+count):walk(child,path)
    else:
        offset=data+struct.unpack_from('>I',raw,at+10)[0];size=struct.unpack_from('>I',raw,offset)[0]
        content=raw[offset+4:offset+4+size];assert len(content)==size
        if flags&1:
            length=struct.unpack_from('>I',content)[0];content=zlib.decompress(content[4:]);assert len(content)==length
        rows.append({'path':path,'record_offset':offset,'stored_bytes':size,'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()})
        if path in wanted:exports[path]=content
walk(0,'');assert len(rows)==400 and set(exports)==wanted
out=BASE/'.device-reference/v2.4.0';out.mkdir(parents=True,exist_ok=False)
for name,content in exports.items():
    path=out/name.lstrip('/');path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
(out/'RESOURCE_MAP.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
print('QRC_VALIDATED=400; SELECTED_QML_EXPORTED=8; FONT_OR_ICON_FILES_EXPORTED=0')
print('REFERENCE_DIR='+str(out))
