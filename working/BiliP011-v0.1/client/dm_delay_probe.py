"""Finite test-only delayed delivery; no media or account data is stored."""
import math
import time

def wait_for_playback(read_state,alive,stop,clock=time.monotonic):
    until=clock()+20
    while clock()<until and not stop.is_set():
        if not alive():return None
        state=read_state();p=state.get('player',{})
        pos=p.get('position')
        if (p.get('loaded') is True and p.get('active') is True and p.get('paused') is False and
            type(pos) in (float,int) and math.isfinite(pos) and 8<=pos<=86400):return pos
        if stop.wait(.2):return None
    return None
