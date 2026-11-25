"""Fresh explicit library/timed-media candidate; no default promotion."""
import argparse,subprocess,sys
from build_awake_trial import BASE,build
from strip_player_artifact import validate_strip_player
def main():
    p=argparse.ArgumentParser();p.add_argument('--media',required=True);p.add_argument('--automated',action='store_true');p.add_argument('--regression',action='store_true');p.add_argument('--build-only',action='store_true');a=p.parse_args()
    import re
    if not re.fullmatch('media-[a-f0-9]{16}',a.media):p.error('Exact immutable media identity required')
    if a.regression and not a.automated:p.error('Regression requires automated mode')
    validate_strip_player(BASE)
    bundle=build(BASE/'out'/a.media,client=True,automated=a.automated,player_protocol=2,ux_state=True,toolbox=a.regression,catalog_probe=a.automated and not a.regression)
    print('BUNDLE='+str(bundle),flush=True)
    if a.build_only:return 0
    subprocess.run([sys.executable,str(BASE/'host/awake_trial.py'),'stage','--bundle',str(bundle)],check=True)
    return subprocess.call([sys.executable,str(BASE/'host/client_oneclick.py'),'--bundle',str(bundle)]+(['--automated'] if a.automated else []))
if __name__=='__main__':raise SystemExit(main())
