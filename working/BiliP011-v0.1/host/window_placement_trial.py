"""Fresh guarded window-fix session, never reuse an archived START.

Automated mode checks the actual DRM output as well as the existing app
captures. Manual mode never autoplays or performs account actions.
"""
import argparse
import re
import subprocess
import sys
from build_awake_trial import BASE, build
from strip_player_artifact import validate_strip_player

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--media',required=True)
    parser.add_argument('--automated',action='store_true')
    parser.add_argument('--build-only',action='store_true')
    args=parser.parse_args()
    if not re.fullmatch('media-[a-f0-9]{16}',args.media):parser.error('Exact media identity required')
    validate_strip_player(BASE)
    bundle=build(BASE/'out'/args.media,client=True,automated=args.automated,
                 player_protocol=2,toolbox=args.automated,ux_state=True,screen_check=args.automated)
    print('BUNDLE='+str(bundle),flush=True)
    if args.build_only:return 0
    subprocess.run([sys.executable,str(BASE/'host/awake_trial.py'),'stage','--bundle',str(bundle)],check=True)
    command=[sys.executable,str(BASE/'host/client_oneclick.py'),'--bundle',str(bundle)]
    if args.automated:command+=['--automated','--scanout-check']
    return subprocess.call(command)

if __name__=='__main__':raise SystemExit(main())
