"""Clean only a hash-identified abandoned cache trial after private-idle checks."""
import argparse,datetime,json,pathlib
from awake_trial import Adb,NATIVE,ROOT,archive
from cache_trial import cleanup_staged
from ion_copy_trial import IDLE_GATE

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=pathlib.Path,required=True)
    path=parser.parse_args().run.resolve()
    if path.parent!=ROOT/'logs' or not path.name.startswith('BiliP011-CacheDecode-'):raise ValueError('Unexpected run identity')
    identity=json.loads((path/'identity.json').read_text())
    log=ROOT/'logs'/('BiliP011-CacheStagingCleanup-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));log.mkdir()
    try:
        safety=(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8')+'\n'+IDLE_GATE
        result=cleanup_staged(Adb(log),safety,identity['directory'],identity['hashes'])
        (log/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
    finally:archive(log)

if __name__=='__main__':main()
