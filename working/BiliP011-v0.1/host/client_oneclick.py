"""Finite client trial. Interactive mode never autoplays; automated mode mutes.

Fresh candidate by default; explicit --bundle only accepts an already staged
unstarted immutable candidate. Device guardian caps the session at 10 minutes.
"""
import argparse,datetime,json,pathlib,subprocess,sys,time
from build_awake_trial import build,BASE,ROOT,NATIVE
from awake_trial import Adb,result_from,command,archive,check_bundle
from client_results import archive_client,crop_captures
from client_soak import collect as soak_collect,evaluate as soak_evaluate

def observe_status(adb,meta,report):
    """Retry one transport timeout of a read-only status, never a device action.

    Raw failure evidence remains untouched. Remote nonzero/schema/identity
    failures still fail immediately; the guardian deadline is not extended.
    """
    try:return result_from(command(adb,meta,'observe',['status']))
    except RuntimeError:
        path=adb.out/('%02d-observe.status.json'%adb.sequence)
        try:status=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):raise
        if status!={'host_exit':None,'remote_exit':None,'timeout':True} or report.get('observation_timeouts',0):raise
        report['observation_timeouts']=1
        print('READ_ONLY_STATUS_TIMEOUT: retry once; original raw/status evidence retained.',flush=True)
        return result_from(command(adb,meta,'observe-retry',['status']))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--bundle',type=pathlib.Path)
    parser.add_argument('--automated',action='store_true',help='Finite candidate-only UI clicks and public-page screenshots; never account/QR')
    parser.add_argument('--scanout-check',action='store_true',help='Require actual DRM screen alignment in both orientations and repeated players')
    parser.add_argument('--soak-seconds',type=int,choices=(0,130),default=0,help='Explicit muted test-only hold; no effect on ordinary manual trials')
    args=parser.parse_args()
    if args.scanout_check and not args.automated:parser.error('Scanout checks require muted automated public pages')
    if args.soak_seconds and not args.automated:parser.error('Soak requires --automated')
    # Frozen AVC OMX + verified 1080P cache-bound retention / size fallback:
    # 89 checks / 47 viewed captures + 129.917s backlight, 20260925-133901.
    # e4ccc8 adds explicit paused/loading rate labels; API/HW/plugin unchanged.
    # 133657: 46.41fps / 60fps source; stable playing/paused rate states pass.
    # 125227 same 60fps source: 46.23 submitted fps vs old 31.40 (125417).
    # 130005 real delayed danmaku/50fps; 130200 full-rate 1080P30;
    # 130721 720P fallback and 130912 cached paused seek/close also pass.
    # 1080P30 meets full-rate gates. 50/60fps use labelled reduced-rate
    # compatibility, NOT a full-source-rate performance pass. HEVC/AV1 are SW.
    # The copied UI remains a fresh, guarded 10-minute candidate every run.
    bundle=args.bundle or build(BASE/'out/media-e4ccc8fa53004efb',client=True,automated=args.automated,player_protocol=2,toolbox=True,soak_seconds=args.soak_seconds)
    meta,_=check_bundle(bundle)
    if bool(meta.get('ui_automation')) != args.automated: raise ValueError('Explicit automation mode must match frozen bundle')
    if args.scanout_check and meta.get('screen_check') is not True:raise ValueError('Screen check requires frozen stable-pose automation')
    if meta.get('soak_seconds',0)!=args.soak_seconds:raise ValueError('Explicit soak mode must match frozen bundle')
    if meta.get('client_adapter')!='v0.2':raise ValueError('Not a Bili client candidate')
    if args.bundle is None:
        subprocess.run([sys.executable,str(BASE/'host/awake_trial.py'),'stage','--bundle',str(bundle)],check=True)
    out=ROOT/'logs'/('BiliP011-Client-OneClick-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir();print('LOG_DIR='+str(out),flush=True)
    (out/'bundle.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    adb=Adb(out);started=False;complete=False;report={'physical_acceptance':False,'permanent_install':False};soak_samples=[]
    if args.scanout_check:report['screen_pose_hold_ms']=12000
    screen_observer=None
    if args.scanout_check:
        from scanout_alignment import Observer
        screen_observer=Observer(adb,meta,out)
    try:
        # Test exact target binaries before changing any factory UI process.
        # This catches options omitted from the reduced private libmpv build.
        subprocess.run([sys.executable,str(BASE/'host/client_native_check.py'),'--bundle',str(bundle)],check=True)
        report['native_preflight_passed']=True
        # A failed start can still have armed the device guardian; cleanup is
        # attempted only for this exact immutable session identity.
        started=True;result_from(command(adb,meta,'start',['start']))
        until=time.monotonic()+35
        while time.monotonic()<until:
            status=result_from(command(adb,meta,'ready',['status']))
            if status['complete']:raise RuntimeError('Candidate ended before ready; inspect device logs')
            if status['ready']:break
            time.sleep(2)
        else:raise RuntimeError('Client did not become ready')
        mode=('automated public UI + muted player checks' if meta.get('player_protocol')==2 else 'automated public UI checks, no playback') if args.automated else 'interactive, no autoplay'
        print('CLIENT_READY: '+mode+'; no automated account/QR page; max 10 min; Exit restores stock.',flush=True)
        report['ready']=True
        until=time.monotonic()+550
        while time.monotonic()<until:
            status=observe_status(adb,meta,report)
            if status['complete']:complete=True;break
            if args.soak_seconds:soak_samples.append(soak_collect(adb,meta))
            if screen_observer:screen_observer.poll()
            # Safe operations can continue on the PC while this observes.
            time.sleep(1 if screen_observer else 5)
    except Exception as exc:
        report['host_error']=type(exc).__name__+': '+str(exc)
        print('HOST_OBSERVATION_ERROR: '+report['host_error'],flush=True)
    finally:
        if started:
            try:
                if not complete:result_from(command(adb,meta,'stop',['stop']))
                until=time.monotonic()+90
                while time.monotonic()<until:
                    status=result_from(command(adb,meta,'restoration',['status']))
                    if status['complete']:complete=True;break
                    time.sleep(2)
                if not complete:raise RuntimeError('Restoration not confirmed; do not rerun')
                report['recovery']=json.loads(status['files']['result.json'])
                # Account directory is NOT below meta['remote']. QR and API
                # stdout are never persisted there. Never pull bili-account.
                adb.run('pull',['pull',meta['remote'],str(out/'device')],timeout=45)
                safety=(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8')
                after=result_from(adb.python('independent-stock',safety+'\ns=stock_snapshot();require_stock(s);print("RESULT="+repr(s))'))
                (out/'independent-stock.json').write_text(json.dumps(after,indent=2),encoding='utf-8')
                report['independent_stock_verified']=True
                if args.automated:
                    report['ui_automation']=json.loads((out/'device/ui-qa-result.json').read_text(encoding='utf-8'))
                    if not report['ui_automation'].get('passed'): report['host_error']='Automated UI checks failed'
                    report['capture_count']=len(crop_captures(out))
            except Exception as exc:report['recovery_error']=type(exc).__name__+': '+str(exc)
        report['recovery_passed']=bool(report.get('recovery',{}).get('passed') and report.get('independent_stock_verified'))
        if screen_observer:
            report['screen_alignment']=screen_observer.result()
            if not report['screen_alignment']['passed']:report.setdefault('host_error','Actual screen alignment coverage failed')
        if args.soak_seconds:
            report['soak']=soak_evaluate(soak_samples)
            (out/'soak-samples.json').write_text(json.dumps(soak_samples,indent=2),encoding='utf-8')
            if not report['soak']['passed']:report.setdefault('host_error','Continuous playback/backlight gate not met')
        (out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');archive_client(out)
    print('RECOVERY_PASSED='+str(report['recovery_passed'])+'; PHYSICAL_ACCEPTANCE=PENDING',flush=True)
    return 0 if report['recovery_passed'] and not report.get('host_error') and not report.get('recovery_error') else 1

if __name__=='__main__':raise SystemExit(main())
