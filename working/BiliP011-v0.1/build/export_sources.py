"""Container-only, auditable source/notice snapshot; never package vendor files.

Source test-font assets are deliberately excluded. They are not required by
the selected no-tests dependency builds. Runtime binaries are not included.
"""
import hashlib,json,pathlib,zipfile

root=pathlib.Path('/work/p011');out=pathlib.Path('/src/out')
lock=json.loads((root/'sources-lock.json').read_text())
files={};excluded=[]
font_suffixes={'.ttf','.ttc','.otf','.otc','.woff','.woff2','.pfa','.pfb','.pcf','.bdf','.dfont','.sfd','.fon','.fnt'}
binary_suffixes={'.o','.a','.so','.dll','.exe','.pyc','.zip','.gz','.bz2','.xz','.tgz'}
for name in sorted(lock):
    source=root/'sources'/name
    archive=root/'downloads'/(name+'.tar')
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=lock[name]['sha256']:raise ValueError('Dependency source identity differs')
    for path in sorted(source.rglob('*')):
        if not path.is_file():continue
        rel=path.relative_to(source)
        if any(x in ('.git','__pycache__','.cache') for x in rel.parts):continue
        dest='dependencies/'+name+'/'+rel.as_posix()
        if path.is_symlink() or path.suffix.lower() in font_suffixes|binary_suffixes:
            excluded.append(dest);continue
        body=path.read_bytes()
        if body[:4] in (b'\x00\x01\x00\x00',b'OTTO',b'ttcf',b'wOFF',b'wOF2'):
            excluded.append(dest);continue
        files[dest]=path
manifest={name:{'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()} for name,path in files.items()}
record={'layer':'PC source-only snapshot','runtime_binaries_included':False,'vendor_files_included':False,
        'source_downloads':lock,'excluded_test_fonts_and_archives':excluded,'files':manifest}
raw=json.dumps(record,sort_keys=True,indent=2).encode();identity=hashlib.sha256(raw).hexdigest()
target=out/('dependency-sources-'+identity[:16]+'.zip')
with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for name,path in files.items():z.write(path,name)
    z.writestr('source-manifest.json',raw)
    z.writestr('README.txt','Source-only snapshot of the pinned private dependency builds, including dav1d. Full upstream license/notice files are preserved. Test fonts, compressed test fixtures, binaries and links are excluded; selected build scripts disable tests. Original archive URLs and SHA-256 values are in source-manifest.json. This is not a vendor firmware image, public binary release or self-contained cross compiler. Bootlin/GCC toolchain materials are separate.\n')
with zipfile.ZipFile(target) as z:
    assert z.testzip() is None
print('SOURCE_ZIP='+str(target));print('FILES='+str(len(files)));print('EXCLUDED='+str(len(excluded)))
print('SHA256='+hashlib.sha256(target.read_bytes()).hexdigest())
