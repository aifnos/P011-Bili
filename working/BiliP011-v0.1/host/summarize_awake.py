"""Derive separate media, power, and process-restoration evidence from raw logs."""
import argparse
import hashlib
import json
import pathlib
import re


def summarize(folder):
    device=folder/'device'
    events=[json.loads(line) for line in (device/'events.jsonl').read_text().splitlines()]
    samples=[e for e in events if e['event']=='SAMPLE']
    restoration=json.loads((device/'result.json').read_text())
    plays=[]
    for path in sorted(device.glob('play-*.stdout.raw')):
        raw=path.read_bytes();text=raw.decode('utf-8','replace')
        match=re.search(r'RESULT loaded=(\d+) maxpos=([0-9.]+).* drops=(-?\d+) ao=(\S+)',text)
        if not match:continue
        number=int(path.name.split('-')[1].split('.')[0])
        starts=[e for e in events if e['event']=='PLAY_STARTED' and e['number']==number]
        ends=[e for e in events if e['event']=='PLAY_EXIT' and e['number']==number]
        start=starts[0]['monotonic'];end=ends[0]['monotonic'] if ends else None
        window=[s for s in samples if start<=s['monotonic'] and (end is None or s['monotonic']<=end)]
        after=[s for s in samples if end is not None and end<=s['monotonic']]
        held=[s for s in window if s['enabled']==0]
        released=next((s for s in after if s['enabled']==1),None)
        off=next((s for s in after if s['enabled']==1 and s['actual_brightness']==0),None)
        plays.append(dict(number=number,position_seconds=float(match[2]),pulse=match[4]=='pulse',drops=int(match[3]),
                          input_exit='EXIT_EVENT' in text,held_samples=len(held),
                          held_sample_span=round(held[-1]['monotonic']-held[0]['monotonic'],3) if held else 0,
                          held_backlight_all_nonzero=bool(held) and all(s['actual_brightness']>0 for s in held),
                          release_after_exit=round(released['monotonic']-end,3) if released else None,
                          backlight_off_after_exit=round(off['monotonic']-end,3) if off else None,
                          continuous_120s_pass=float(match[2])>=119 and bool(held) and len(held)>=90 and all(s['actual_brightness']>0 for s in held),
                          stdout_sha256=hashlib.sha256(raw).hexdigest()))
    result=dict(plays=plays,idle_seconds_always_60=all(s['seconds']==60 for s in samples),
                process_restore_pass=restoration['passed'],physical_acceptance='pending_user',
                note='Probe exit 0 and restoration passed are not full-duration or physical playback acceptance.')
    target=folder/'derived-summary.json'
    if target.exists():raise ValueError('Derived summary already exists; preserve it')
    target.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder',type=pathlib.Path);summarize(p.parse_args().folder)
