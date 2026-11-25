"""Generate a local, deterministic-shape synthetic AVC fixture; never uses ADB."""
import datetime,hashlib,json,pathlib,shutil,subprocess,tempfile

def main():
    base=pathlib.Path(__file__).resolve().parents[1]
    ffmpeg=shutil.which('ffmpeg');ffprobe=shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:raise ValueError('Host FFmpeg and FFprobe required')
    # mkdtemp is inside the workspace. Generated video is not user media.
    work=pathlib.Path(tempfile.mkdtemp(prefix='cache-fixture-build-',dir=base/'out'))
    video=work/'input.mp4'
    command=[ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc2=size=1920x1080:rate=60',
             '-frames:v','240','-an','-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p',
             '-bf','2','-g','60','-keyint_min','60','-sc_threshold','0','-movflags','+faststart',str(video)]
    subprocess.run(command,check=True,timeout=60)
    details=json.loads(subprocess.check_output([ffprobe,'-v','error','-show_streams','-of','json',str(video)],timeout=10))
    stream=details['streams'][0]
    if len(details['streams'])!=1 or stream['codec_name']!='h264' or stream['width']!=1920 or stream['height']!=1080 or stream['r_frame_rate']!='60/1' or stream['nb_frames']!='240':raise ValueError('Unexpected synthetic fixture')
    digest=hashlib.sha256(video.read_bytes()).hexdigest();target=base/'out'/('cache-fixture-'+digest[:16])
    if target.exists():raise ValueError('Do not overwrite an existing fixture')
    # Same parent and resolved workspace targets; this moves only this newly
    # created synthetic build directory, never a pre-existing user directory.
    if work.resolve().parent!=base/'out' or target.parent!=base/'out':raise ValueError('Unexpected build path')
    work.rename(target)
    record={'sha256':digest,'frames':240,'width':1920,'height':1080,'fps':60,'synthetic':True,
            'ffmpeg_version':subprocess.check_output([ffmpeg,'-version'],text=True,timeout=5).splitlines()[0],
            'ffprobe':details,'created':datetime.datetime.now().isoformat()}
    (target/'fixture.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    print('FIXTURE='+str(target));print('SHA256='+digest)

if __name__=='__main__':main()
