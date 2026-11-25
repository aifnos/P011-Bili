"""Explicit UX candidate only; existing default player is not promoted.

Fresh guarded session on every run. No autoplay in interactive mode.
--automated explicitly selects bounded, muted, public-page checks.
"""
import argparse
import subprocess
import sys
from build_awake_trial import BASE,build
from strip_player_artifact import validate_strip_player

MEDIA='media-2fa79fdc627e3238'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--automated',action='store_true')
    parser.add_argument('--build-only',action='store_true',help='PC only, no ADB access')
    parser.add_argument('--state-probe',action='store_true',help='Explicit muted isolated resume/restart/history acceptance')
    parser.add_argument('--soak-seconds',type=int,choices=(0,130),default=0,help='Automated continuous playback across the stock idle timeout')
    parser.add_argument('--soak-bvid',default='',help='Public fixed reproduction source; requires the automated 130-second soak')
    args=parser.parse_args()
    validate_strip_player(BASE)
    if args.state_probe and not args.automated:parser.error('State probe requires --automated')
    if args.soak_seconds and (not args.automated or args.state_probe):parser.error('Soak requires the full automated UI trial')
    bundle=build(BASE/'out'/MEDIA,client=True,automated=args.automated,player_protocol=2,toolbox=not args.state_probe,ux_state=True,ux_probe=args.state_probe,soak_seconds=args.soak_seconds,soak_bvid=args.soak_bvid)
    print('UX_CANDIDATE='+str(bundle),flush=True)
    if args.build_only:return 0
    subprocess.run([sys.executable,str(BASE/'host/awake_trial.py'),'stage','--bundle',str(bundle)],check=True)
    command=[sys.executable,str(BASE/'host/client_oneclick.py'),'--bundle',str(bundle)]
    if args.automated:command.append('--automated')
    if args.soak_seconds:command+=['--soak-seconds',str(args.soak_seconds)]
    return subprocess.call(command)

if __name__=='__main__':raise SystemExit(main())
