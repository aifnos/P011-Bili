"""Explicit reduced-rate evidence, never a full-source-rate or physical pass."""
import math


def evaluate(rate,period,driver_passed):
    if type(period) is not int or period not in (0,2,3):
        raise ValueError('Unknown cached compatibility policy')
    fields=('encoded_annexb','encoded_disposable','encoded_reference','encoded_nonref_skipped',
            'encoded_invalid','encoded_unsupported','consumed_frames','drops','decoder_drops')
    if any(type(rate.get(k)) is not int or rate[k]<0 for k in fields):
        raise ValueError('Missing compatibility counters')
    for key in ('source_fps','elapsed_seconds','consumed_fps','position_advance'):
        if type(rate.get(key)) not in (int,float) or not math.isfinite(rate[key]) or rate[key]<0:
            raise ValueError('Invalid compatibility measurement')
    n=rate['encoded_annexb'];d=rate['encoded_disposable'];s=rate['encoded_nonref_skipped']
    seconds=rate['elapsed_seconds'];fps=rate['source_fps']
    if fps not in (50,60) or not 11.9<=seconds<=13 or not 0<s<=d<=n or rate['encoded_reference']>n-s:
        raise ValueError('Not a bounded high-frame-rate retention experiment')
    if abs(rate['consumed_frames']/seconds-rate['consumed_fps'])>1e-7:
        raise ValueError('Compatibility frame arithmetic differs')
    # The window can start/end within a retention period; atomically loaded
    # counters can straddle one callback. Never interpret these as a frame map.
    desired_skips=d if period==0 else d*(period-1)/period
    policy_consistent=abs(s-desired_skips)<=2 and not rate['encoded_invalid'] and not rate['encoded_unsupported']
    retained_fps=fps*(n-s)/n
    source_rate_consistent=.95*fps<=n/seconds<=1.05*fps
    clock_consistent=.94<=rate['position_advance']/seconds<=1.06
    drops=rate['drops']+rate['decoder_drops']
    adequate=rate['consumed_fps']>=retained_fps*.95 and drops<=retained_fps*seconds*.01
    return dict(keep_every=period,source_fps=fps,consumed_fps=rate['consumed_fps'],
                measured_input_fps=n/seconds,estimated_retained_fps=retained_fps,
                deliberately_skipped=s,recorded_late_drops=drops,policy_consistent=bool(policy_consistent),
                source_rate_consistent=bool(source_rate_consistent),clock_consistent=bool(clock_consistent),
                compatibility_rate_met=bool(driver_passed and policy_consistent and source_rate_consistent and clock_consistent and adequate),
                full_source_rate_passed=False,physical_acceptance=False)
