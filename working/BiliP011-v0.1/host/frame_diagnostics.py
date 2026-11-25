"""Read-only accounting for phase peaks and the existing drop counter parts.

Uses one atomic media-state snapshot, not the separately written player-state
total. Includes observed warmup; NEVER changes the playback pass/fail window.
These parts split existing counted drops, not every possible internal sink loss.
"""
import math

PHASES=('input','status','layout','pacer','upload','overlay','swap')
FIELDS=('count','total_us','max_us','over_33ms','over_100ms','last_slow_position_ms')
COMPONENTS=('hardware_sink_qos_drops','hardware_shared_slot_drops','hardware_ui_ready_drops')
GLYPHS=('glyph_rasterizations','glyph_metric_loads','glyph_evictions','glyph_quad_calls')

def analyze(samples):
    selected=[]
    keys=tuple('phase_'+p+'_'+f for p in PHASES for f in FIELDS)+COMPONENTS+('hardware_total_drops',)+GLYPHS
    cumulative=[k for k in keys if not k.endswith('last_slow_position_ms')]
    for row in samples:
        s=row.get('player',{})
        if s.get('active') is not True or s.get('loaded') is not True or s.get('hardware_verified') is not True:continue
        if any(type(s.get(k)) is not int or s[k]<0 for k in keys):return dict(available=False,reason='missing_or_invalid_counters')
        pos=s.get('position')
        if type(pos) not in (int,float) or not math.isfinite(pos) or pos<0:return dict(available=False,reason='invalid_position')
        if sum(s[k] for k in COMPONENTS)!=s['hardware_total_drops']:return dict(available=False,reason='component_total_mismatch')
        if selected and any(s[k]<selected[-1][k] for k in cumulative):return dict(available=False,reason='counter_reset')
        selected.append(s)
    if len(selected)<2:return dict(available=False,reason='insufficient_samples')
    first,last=selected[0],selected[-1]
    events=[]
    for before,after in zip(selected,selected[1:]):
        drops={k:after[k]-before[k] for k in COMPONENTS}
        if not any(drops.values()):continue
        phases={p:{'new_over_33ms':after['phase_'+p+'_over_33ms']-before['phase_'+p+'_over_33ms'],
                   'max_active_us':after['phase_'+p+'_max_us'],
                   'last_slow_position_ms':after['phase_'+p+'_last_slow_position_ms']}
                for p in PHASES if after['phase_'+p+'_over_33ms']>before['phase_'+p+'_over_33ms']}
        events.append(dict(position_from=before['position'],position_to=after['position'],drop_deltas=drops,
                           slow_phases=phases,glyph_deltas={k:after[k]-before[k] for k in GLYPHS}))
    return dict(available=True,scope='all_observed_active_hardware_including_warmup',samples=len(selected),
                drop_totals={k:last[k] for k in COMPONENTS},
                observed_drop_deltas={k:last[k]-first[k] for k in COMPONENTS},
                phases={p:{f:last['phase_'+p+'_'+f] for f in FIELDS} for p in PHASES},
                glyph_totals={k:last[k] for k in GLYPHS},events=events)
