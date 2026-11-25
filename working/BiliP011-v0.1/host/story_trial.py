"""Fresh guarded Story + direct controls acceptance; no permanent install."""
import argparse,re,subprocess,sys
from build_awake_trial import BASE,build
from strip_player_artifact import validate_strip_player

def main():
    p=argparse.ArgumentParser();p.add_argument('--media',required=True);p.add_argument('--automated',action='store_true');p.add_argument('--build-only',action='store_true');a=p.parse_args()
    if not re.fullmatch('media-[a-f0-9]{16}',a.media):p.error('Exact media identity required')
    validate_strip_player(BASE)
    bundle=build(BASE/'out'/a.media,client=True,automated=a.automated,player_protocol=2,ux_state=True,story_probe=a.automated)
    print('BUNDLE='+str(bundle),flush=True)
    if a.build_only:return 0
    subprocess.run([sys.executable,str(BASE/'host/awake_trial.py'),'stage','--bundle',str(bundle)],check=True)
    return subprocess.call([sys.executable,str(BASE/'host/client_oneclick.py'),'--bundle',str(bundle)]+(['--automated'] if a.automated else []))
if __name__=='__main__':raise SystemExit(main())
