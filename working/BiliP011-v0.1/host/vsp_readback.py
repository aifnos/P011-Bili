"""Strict numeric-only evidence for an explicit bounded driver GET query.

The reported level is not an external measurement of physical clock rate.
"""


def evaluate_readback(value):
    fields=('schema','stride','limit','eligible_configurations','skipped_configurations','calls','accepted',
            'getter_missing','return_failed','errno_failed','invalid_level','clock_errors','wall_ns','max_ns')
    fields+=tuple('level'+str(i) for i in range(16))
    if (type(value) is not dict or set(value)!=set(fields) or
            any(type(v) is not int or not 0<=v<=18446744073709551615 for v in value.values())):
        return {'evidence_complete':False}
    valid=(value['schema']==2 and value['stride']==64 and value['limit']==32 and
           5<=value['calls']==min(32,(value['eligible_configurations']+63)//64) and
           value['calls']==value['accepted']==sum(value['level'+str(i)] for i in range(16)) and
           all(value[k]==0 for k in ('getter_missing','return_failed','errno_failed','invalid_level','clock_errors')) and
           0<=value['max_ns']<=value['wall_ns']<=value['max_ns']*value['calls'])
    return {'evidence_complete':bool(valid),'driver_reported_levels':{str(i):value['level'+str(i)] for i in range(16) if value['level'+str(i)]},
            'sample_point':'after_successful_original_frequency_configuration',
            'calls':value['calls'],'maximum_query_ms':value['max_ns']/1000000,
            'mean_query_ms':value['wall_ns']/max(1,value['calls'])/1000000,
            'physical_clock_measured':False,'frequency_changed':False}
