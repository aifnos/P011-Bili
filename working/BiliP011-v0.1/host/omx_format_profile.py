"""Bounded numerical OMX port readback evidence (also runs on Python 3.5)."""
FORMAT_FIELDS = ('stage','port','width','height','stride_bits','slice_height',
                 'fps_q16','caps_n','caps_d','compression','color','buffers',
                 'buffer_bytes','error')


def check_format_shape(value):
    if type(value) is not dict or set(value) != {'schema','count','overflow','invalid','records'}:
        raise ValueError('Unknown OMX format fields')
    for key in ('schema','count','overflow','invalid'):
        if type(value[key]) is not int or not 0 <= value[key] <= 4294967295:
            raise ValueError('Invalid OMX format counter')
    rows = value['records']
    if value['schema'] != 1 or type(rows) is not list or len(rows) != value['count'] or len(rows) > 24:
        raise ValueError('OMX format schema or bound differs')
    for row in rows:
        if type(row) is not list or len(row) != len(FORMAT_FIELDS) or any(type(x) is not int or not 0 <= x <= 4294967295 for x in row):
            raise ValueError('Non-numeric OMX port evidence')
        if row[0] not in (1,2,3):
            raise ValueError('Unknown OMX format observation stage')


def inspect_format(value, source_fps=None):
    check_format_shape(value)
    records = [dict(zip(FORMAT_FIELDS, row)) for row in value['records']]
    complete = bool(records) and not value['overflow'] and not value['invalid'] and len(records) % 3 == 0
    groups = []
    for i in range(0,len(records)-2,3):
        request, readback, output = records[i:i+3]
        sequence = (request['stage'],readback['stage'],output['stage']) == (1,2,3)
        sequence = sequence and request['error'] == 0 and request['port'] == readback['port'] and output['port'] != readback['port']
        sequence = sequence and all((r['caps_n'],r['caps_d']) == (request['caps_n'],request['caps_d']) for r in (readback,output))
        success = readback['error'] == 0 and output['error'] == 0
        matching = all(request[k] == readback[k] for k in ('width','height','fps_q16','compression','color'))
        caps_match = bool(request['caps_d']) and abs(request['fps_q16']/65536.0-request['caps_n']/request['caps_d']) <= 1.1/65536
        source_match = source_fps is None or bool(request['caps_d']) and abs(request['caps_n']/request['caps_d']-source_fps) < .001
        groups.append(dict(request=request,input_readback=readback,startup_output_readback=output,
                           sequence_valid=bool(sequence),calls_succeeded=success,
                           input_matches_requested=bool(success and matching),
                           requested_fps_matches_caps=bool(caps_match),caps_match_source=bool(source_match)))
        complete = complete and sequence
    # A captured disagreement is useful evidence, NOT a playback success or a
    # reason to relabel a failed call as accepted. Output is startup-only here.
    return dict(evidence_complete=bool(complete),record_count=len(records),
                calls_succeeded=bool(complete and all(g['calls_succeeded'] for g in groups)),
                input_matches_requested=bool(complete and all(g['input_matches_requested'] for g in groups)),
                requested_fps_matches_caps=bool(complete and all(g['requested_fps_matches_caps'] for g in groups)),
                caps_match_source=bool(complete and all(g['caps_match_source'] for g in groups)),
                existing_calls_only=True,output_is_startup_definition_only=True,
                performance_passed=False,groups=groups)
