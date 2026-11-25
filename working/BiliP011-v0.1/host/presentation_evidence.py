"""Audit v1 Wayland feedback, distinct hardware video identities and timing.

Compositor feedback is not an optical measurement. No source-rate gate is
changed here, and a UI redraw must never count as another decoded video frame.
"""
import math
import statistics

FIELDS={'schema','protocol_version','clock_id','commits','video_frames','capacity_skips',
        'invalid_timestamps','clock_errors','global_removed','pending_limit','row_limit',
        'physical_optical_measurement','rows'}

def percentile(values, fraction):
    ordered=sorted(values)
    return ordered[max(0,math.ceil(len(ordered)*fraction)-1)] if ordered else None

def analyze(data):
    absent={'evidence_complete':False,'physical_optical_measurement':False,
            'display_ceiling_established':False}
    if type(data) is not dict or set(data)!=FIELDS:return dict(absent,error='shape')
    numeric=FIELDS-{'rows','global_removed','physical_optical_measurement'}
    if any(type(data[k]) is not int or not 0<=data[k]<2**63 for k in numeric):return dict(absent,error='numeric')
    if (data['schema']!=1 or data['protocol_version']!=1 or data['clock_id']!=1 or
            data['global_removed'] is not False or data['physical_optical_measurement'] is not False or
            data['pending_limit']!=256 or data['row_limit']!=32768 or
            any(data[k] for k in ('capacity_skips','invalid_timestamps','clock_errors'))):return dict(absent,error='observer')
    rows=data['rows']
    if type(rows) is not list or not 100<=len(rows)<=32768:return dict(absent,error='row_count')
    seen=set();outcomes={1:0,2:0,3:0};flags={};video_identity={}
    for row in rows:
        if type(row) is not list or len(row)!=11 or any(type(x) is not int or not -(2**63)<=x<2**63 for x in row):return dict(absent,error='row_shape')
        kind,commit,video,serial,pts,submit,present,refresh,sequence,flag,playing=row
        if (kind not in outcomes or not 1<=commit<=data['commits'] or commit in seen or
                not 0<=video<=data['video_frames'] or not 0<=serial<2**32 or pts< -1 or
                submit<=0 or min(present,refresh,sequence,flag)<0 or flag>15 or playing not in (0,1)):
            return dict(absent,error='row_value')
        if kind==1 and present<submit:return dict(absent,error='clock_order')
        if kind!=1 and any((present,refresh,sequence,flag)):return dict(absent,error='nonpresentation_timestamp')
        if video:
            if pts<0 or video_identity.setdefault(video,(serial,pts))!=(serial,pts):return dict(absent,error='video_identity')
        seen.add(commit);outcomes[kind]+=1
        if kind==1:flags[str(flag)]=flags.get(str(flag),0)+1
    if len(rows)!=data['commits']:return dict(absent,error='missing_commits')
    # Choose one contiguous playing interval; never join across pause/seek or
    # buffering gaps. Discarded commits still belong to the same interval.
    groups=[];group=[];last_present=0;last_pts=-1
    for row in sorted(rows,key=lambda r:r[1]):
        eligible=row[10]==1 and row[2]>0 and row[4]>=6000000
        if not eligible or row[4]<last_pts or (row[0]==1 and last_present and row[6]-last_present>2000000000):
            if group:groups.append(group)
            group=[];last_present=0;last_pts=-1
        if not eligible:continue
        group.append(row);last_pts=row[4]
        if row[0]==1:last_present=row[6]
    if group:groups.append(group)
    group=max(groups,key=lambda g:sum(r[0]==1 for r in g),default=[])
    presented=sorted((r for r in group if r[0]==1),key=lambda r:(r[6],r[1]))
    unique=[];identities=set()
    for row in presented:
        if row[2] not in identities:unique.append(row);identities.add(row[2])
    if len(unique)<100:return dict(absent,error='insufficient_video',outcomes=outcomes,flags=flags)
    elapsed=(unique[-1][6]-unique[0][6])/1e9
    if elapsed<8:return dict(absent,error='short_interval',outcomes=outcomes,flags=flags)
    intervals=[(b[6]-a[6])/1e6 for a,b in zip(unique,unique[1:])]
    if min(intervals)<=0:return dict(absent,error='timestamp_order')
    sequence_ok=all(b[8]>a[8] for a,b in zip(unique,unique[1:]))
    hardware_timing=all(r[9]&7==7 for r in presented)
    inferred_refresh=(unique[-1][8]-unique[0][8])/elapsed if sequence_ok else None
    refresh_ns=[r[7] for r in presented if r[7]>0]
    return dict(evidence_complete=True,physical_optical_measurement=False,
        display_ceiling_established=bool(hardware_timing and sequence_ok and inferred_refresh and 1<inferred_refresh<1000),
        hardware_timestamped_vsync=hardware_timing,refresh_sequence_valid=sequence_ok,
        compositor_refresh_hz=inferred_refresh,reported_refresh_hz=1e9/statistics.median(refresh_ns) if refresh_ns else None,
        compositor_presented_video_fps=(len(unique)-1)/elapsed,elapsed_seconds=elapsed,
        distinct_video_frames=len(unique),presented_commits=len(presented),redraw_presentations=len(presented)-len(unique),
        discarded_commits=sum(r[0]==2 for r in group),all_outcomes={str(k):v for k,v in outcomes.items()},
        flags=flags,frame_interval_ms={'median':statistics.median(intervals),'p95':percentile(intervals,.95),
                                     'p99':percentile(intervals,.99),'maximum':max(intervals)},
        scope='compositor_feedback_for_one_contiguous_hardware_video_interval')
