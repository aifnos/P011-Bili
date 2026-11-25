"""Host-only, numeric evidence for a single private xdg window.

WAYLAND_DEBUG can include input and other private data. Never return raw lines,
titles, app IDs, key events or free-form error messages. A sync callback is not
evidence of an xdg configure. This checks the first buffer COMMIT, not frame rate
or the appearance of the physical screen.
"""
import re

MAX_TRACE_CHARS = 2 * 1024 * 1024
MAX_EVENTS = 512
LINE = re.compile(r'^\[\s*[0-9.]+\]\s*(->\s*)?([a-z0-9_]+)@([0-9]+)\.([a-z0-9_]+)\((.*)\)\s*$')
ROLE = re.compile(r'new id (zxdg_surface_v6|xdg_surface)@([0-9]{1,10}),\s*wl_surface@([0-9]{1,10})')
BUFFER = re.compile(r'(?:wl_buffer@([0-9]+)|(nil)),\s*-?[0-9]+,\s*-?[0-9]+')
ERROR = re.compile(r'[a-z0-9_]+@[0-9]+,\s*([0-9]+),')


def analyze(trace):
    report = {'schema': 1, 'passed': False, 'status': 'incomplete_trace',
              'events': [], 'physical_acceptance': False}
    if not isinstance(trace, str) or len(trace) > MAX_TRACE_CHARS:
        report['status'] = 'trace_size_rejected'
        return report
    events = report['events']
    for line in trace.splitlines():
        match = LINE.fullmatch(line)
        if not match:
            continue
        arrow, interface, object_id, method, args = match.groups()
        if len(object_id) > 10 or int(object_id) > 0xffffffff:
            continue
        object_id = int(object_id)
        event = None
        if arrow and (interface, method) in (
                ('zxdg_shell_v6', 'get_xdg_surface'), ('xdg_wm_base', 'get_xdg_surface')):
            role = ROLE.fullmatch(args)
            if (role and max(int(role[2]),int(role[3])) <= 0xffffffff
                    and role[1] == ('zxdg_surface_v6' if interface == 'zxdg_shell_v6' else 'xdg_surface')):
                event = {'kind': 'role', 'xdg': int(role[2]), 'surface': int(role[3])}
        elif interface in ('zxdg_surface_v6', 'xdg_surface'):
            if ((method == 'configure' and not arrow) or (method == 'ack_configure' and arrow)) and re.fullmatch(r'[0-9]{1,10}', args):
                if int(args) <= 0xffffffff:
                    event = {'kind': method, 'xdg': object_id, 'serial': int(args)}
        elif arrow and interface == 'wl_surface':
            if method == 'commit' and not args:
                event = {'kind': 'commit', 'surface': object_id}
            elif method == 'attach':
                buffer = BUFFER.fullmatch(args)
                if buffer:
                    event = {'kind': 'attach', 'surface': object_id, 'has_buffer': buffer[1] is not None}
        elif not arrow and interface == 'wl_display' and method == 'error':
            error = ERROR.match(args)
            if error and len(error[1]) <= 10:
                event = {'kind': 'display_error', 'code': int(error[1])}
        if event is not None:
            if len(events) == MAX_EVENTS:
                report['status'] = 'event_limit_rejected'
                return report
            events.append(event)
    roles = [e for e in events if e['kind'] == 'role']
    # Cursor surfaces are ignored; two xdg roles would make this probe ambiguous.
    if len(roles) != 1:
        report['status'] = 'missing_or_ambiguous_role'
        return report
    role = roles[0]
    surface, xdg = role['surface'], role['xdg']
    configured = []
    valid_acks = 0
    invalid_acks = 0
    has_buffer = False
    empty_commit_seen = False
    first_buffer_commit = None
    eligible_at_first_commit = False
    role_seen = False
    for index, event in enumerate(events):
        kind = event['kind']
        if kind == 'role':
            role_seen = True
        elif kind == 'configure' and event['xdg'] == xdg and role_seen:
            configured.append(event['serial'])
        elif kind == 'ack_configure' and event['xdg'] == xdg and role_seen:
            if event['serial'] in configured:
                valid_acks += 1
                # An acknowledgement consumes this serial and earlier configures.
                del configured[:configured.index(event['serial'])+1]
            else:
                invalid_acks += 1
        elif kind == 'attach' and event['surface'] == surface and role_seen:
            has_buffer = event['has_buffer']
        elif kind == 'commit' and event['surface'] == surface and role_seen:
            if not has_buffer and first_buffer_commit is None:
                empty_commit_seen = True
            elif has_buffer and first_buffer_commit is None:
                first_buffer_commit = index
                eligible_at_first_commit = empty_commit_seen and valid_acks > 0 and invalid_acks == 0
    report.update({'surface': surface, 'xdg': xdg, 'empty_commit_seen': empty_commit_seen,
                   'valid_ack_count': valid_acks, 'invalid_ack_count': invalid_acks,
                   'first_buffer_commit_event': first_buffer_commit,
                   'configured_before_first_buffer_commit': eligible_at_first_commit})
    if any(e['kind'] == 'display_error' for e in events):
        report['status'] = 'display_protocol_error'
    elif first_buffer_commit is None:
        report['status'] = 'no_buffer_commit'
    elif not eligible_at_first_commit:
        report['status'] = 'unconfigured_buffer_commit'
    elif invalid_acks:
        report['status'] = 'invalid_acknowledgement'
    else:
        report['status'] = 'configured_before_first_buffer_commit'
        report['passed'] = True
    return report


def probe_passed(report):
    """No single probe or GL flag may overrule missing protocol/restoration proof."""
    probe = report.get('probe') or {}
    process = report.get('process') or {}
    return bool(probe.get('passed') is True and probe.get('frames', 0) >= 60
                and probe.get('drawable') == [800, 268] and probe.get('rgba_bits') == [8, 8, 8, 8]
                and probe.get('gl_error') == 0 and process.get('exit') == 0
                and process.get('timeout') is False and report.get('stock_unchanged') is True
                and (report.get('protocol_audit') or {}).get('passed') is True)
