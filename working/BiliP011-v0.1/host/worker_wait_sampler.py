"""Python 3.5 read-only sampler of ONE exact diagnostic child, never the UI.

Embedded in the finite cached-worker helper. No command line, environment,
network, memory, user string, kernel address, or arbitrary file is exported.
Sampling is observational and its CPU/wall overhead is reported separately.
"""
import os
import re
import threading
import time


def proc_stat(raw):
    end = raw.rfind(')')
    if end < 0 or len(raw) > 4096:
        raise ValueError('Invalid proc stat')
    fields = raw[end + 2:].split()
    if len(fields) < 39 or fields[0] not in 'RSDZTtXxKWPIN':
        raise ValueError('Incomplete proc stat')
    return dict(state=fields[0], parent=int(fields[1]), user=int(fields[11]),
                system=int(fields[12]), start=int(fields[19]), cpu=int(fields[36]),
                priority=int(fields[37]), policy=int(fields[38]))


def safe_symbol(value):
    return value if re.match(r'^[A-Za-z0-9_.:-]{1,64}$', value) else 'other'


def kernel_symbols(raw):
    # Ignore addresses/offsets. Only retain kernel function identifiers.
    return [safe_symbol(m.group(1)) for m in
            re.finditer(r'\] ([A-Za-z_][A-Za-z0-9_.]*)\+0x[0-9a-f]+/0x[0-9a-f]+', raw)]


def syscall_identity(raw, fd_path):
    fields = raw.split()
    if fields == ['running']:
        return 'running'
    if not fields or not re.match(r'^-?[0-9]{1,4}$', fields[0]):
        return 'unavailable'
    number = int(fields[0])
    if number < 0:
        return 'not_in_syscall'
    result = 'syscall_' + str(number)
    # ARM EABI ioctl. Inspect only fd identity and a fixed known request code;
    # never export the remaining arguments, stack or instruction pointers.
    if number == 54 and len(fields) >= 3:
        try:
            descriptor, request = int(fields[1], 0), int(fields[2], 0)
            if 0 <= descriptor < 65536 and fd_path(descriptor) == '/dev/sprd_vsp':
                return {0x6d07: 'vsp_poll_complete', 0x6d05: 'vsp_acquire'}.get(request, 'vsp_other_ioctl')
        except (OSError, ValueError):
            pass
    return result


def bounded_read(path, limit=4096):
    with open(path, 'r') as source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Oversized proc/sys record')
    return raw


class WorkerWaitSampler:
    def __init__(self, parent, directory):
        if type(parent) is not int or parent <= 1 or not re.match(
                r'^/mnt/data/p011-toolbox/bili-seek-probe-[a-f0-9]{24}$', directory):
            raise ValueError('Not an exact owned diagnostic')
        self.parent = parent
        self.parent_start = proc_stat(bounded_read('/proc/%d/stat' % parent))['start']
        self.executable = directory + '/bili-hw'
        self.pid = None
        self.start_time = None
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run)
        self.thread.daemon = True
        self.result = dict(enabled=True, interval_seconds=1.0, max_samples=50,
                           identity_rejected=False, worker_observed=False,
                           children_interface=True,
                           samples=0, read_errors=0, sampling_wall_seconds=0.,
                           process_cpu_seconds=0., threads={}, clocks={})
        self.thread.start()

    def read(self, path, limit=4096):
        try:
            return bounded_read(path, limit)
        except (OSError, ValueError):
            self.result['read_errors'] += 1
            return ''

    def exact_worker(self):
        parent_stat = proc_stat(bounded_read('/proc/%d/stat' % self.parent))
        if parent_stat['start'] != self.parent_start:
            raise ValueError('Driver identity changed')
        if self.pid is None:
            path = '/proc/%d/task/%d/children' % (self.parent, self.parent)
            if os.path.exists(path):
                children = bounded_read(path).split()
            else:
                # CONFIG_CHECKPOINT_RESTORE may omit the children interface.
                # Discover once using PPID; never read command line/environ.
                self.result['children_interface'] = False
                names = os.listdir('/proc')
                if len(names) > 8192:
                    raise ValueError('Unbounded proc discovery')
                children = []
                for name in names:
                    if not name.isdigit():
                        continue
                    try:
                        if proc_stat(bounded_read('/proc/' + name + '/stat'))['parent'] == self.parent:
                            children.append(name)
                    except OSError:
                        continue
            if len(children) > 4:
                raise ValueError('Unexpected driver child count')
            for value in children:
                pid = int(value)
                try:
                    if os.readlink('/proc/%d/exe' % pid) != self.executable:
                        continue
                    info = proc_stat(bounded_read('/proc/%d/stat' % pid))
                    if info['parent'] != self.parent:
                        continue
                    self.pid, self.start_time = pid, info['start']
                    self.result['worker_observed'] = True
                    break
                except OSError:
                    continue
        if self.pid is None:
            return False
        info = proc_stat(bounded_read('/proc/%d/stat' % self.pid))
        if info['start'] != self.start_time or info['parent'] != self.parent or \
                os.readlink('/proc/%d/exe' % self.pid) != self.executable:
            raise ValueError('Worker identity changed')
        return True

    def clock_sample(self):
        # Read only already-available interfaces. Never mount debugfs or write
        # a governor/frequency/boost knob. Clock names are hardware metadata.
        path = '/sys/kernel/debug/clk/clk_summary'
        if os.path.isfile(path):
            raw = self.read(path, 131072)
            for line in raw.splitlines():
                fields = line.split()
                if len(fields) >= 4 and re.search('vsp|vcodec', fields[0], re.I) and all(
                        value.isdigit() for value in fields[1:4]):
                    key = 'clk_' + safe_symbol(fields[0])
                    rates = self.result['clocks'].setdefault(key, {})
                    rate = str(int(fields[3]))
                    rates[rate] = rates.get(rate, 0) + 1
        for cpu in range(4):
            path = '/sys/devices/system/cpu/cpu%d/cpufreq/scaling_cur_freq' % cpu
            if os.path.isfile(path):
                raw = self.read(path).strip()
                if raw.isdigit():
                    rates = self.result['clocks'].setdefault('cpu%d_khz' % cpu, {})
                    rates[raw] = rates.get(raw, 0) + 1

    def sample(self):
        if not self.exact_worker():
            return
        task_root = '/proc/%d/task' % self.pid
        names = os.listdir(task_root)
        if len(names) > 64:
            raise ValueError('Unexpected thread count')
        stamp = time.monotonic()
        for name in names:
            if not name.isdigit():
                continue
            root = task_root + '/' + name
            try:
                info = proc_stat(bounded_read(root + '/stat'))
                comm = safe_symbol(bounded_read(root + '/comm').strip())
            except OSError:
                continue
            wchan = safe_symbol(self.read(root + '/wchan').strip()) if os.path.isfile(root + '/wchan') else 'unavailable'
            key = name + '_' + str(info['start'])
            if key not in self.result['threads'] and len(self.result['threads']) >= 256:
                raise ValueError('Unbounded thread churn')
            entry = self.result['threads'].setdefault(key, dict(
                name=comm, samples=0, states={}, waits={}, stacks={}, syscalls={},
                wchan_available=os.path.isfile(root + '/wchan'),
                schedstat_available=os.path.isfile(root + '/schedstat'),
                first_user=info['user'], first_system=info['system'], first_at=stamp))
            entry['samples'] += 1
            entry['last_user'], entry['last_system'], entry['last_at'] = info['user'], info['system'], stamp
            entry['policy'], entry['priority'] = info['policy'], info['priority']
            for group, value in (('states', info['state']), ('waits', wchan)):
                entry[group][value] = entry[group].get(value, 0) + 1
            sched = self.read(root + '/schedstat').split() if entry['schedstat_available'] else []
            if len(sched) == 3 and all(value.isdigit() for value in sched):
                for field, value in zip(('run_ns', 'runqueue_ns', 'slices'), sched):
                    entry.setdefault('first_' + field, int(value))
                    entry['last_' + field] = int(value)
            for symbol in kernel_symbols(self.read(root + '/stack', 8192)):
                entry['stacks'][symbol] = entry['stacks'].get(symbol, 0) + 1
            call = syscall_identity(self.read(root + '/syscall'),
                                    lambda fd: os.readlink('/proc/%d/fd/%d' % (self.pid, fd)))
            entry['syscalls'][call] = entry['syscalls'].get(call, 0) + 1
            # Do not retain observations after this thread ID was reused.
            if proc_stat(bounded_read(root + '/stat'))['start'] != info['start']:
                raise ValueError('Thread identity changed')
        self.clock_sample()
        self.result['samples'] += 1

    def run(self):
        cpu = time.process_time()
        began = time.monotonic()
        self.result['ticks_per_second'] = os.sysconf('SC_CLK_TCK')
        for unused in range(50):
            if self.stop_event.is_set():
                break
            at = time.monotonic()
            try:
                self.sample()
            except OSError:
                # Natural child shutdown may race a read, but never retarget.
                self.result['read_errors'] += 1
                if self.pid is not None:
                    break
            except (ValueError, TypeError):
                self.result['identity_rejected'] = True
                break
            self.result['sampling_wall_seconds'] += time.monotonic() - at
            if self.stop_event.wait(1.0):
                break
        self.result['process_cpu_seconds'] = time.process_time() - cpu
        self.result['elapsed_seconds'] = time.monotonic() - began

    def finish(self):
        self.stop_event.set()
        self.thread.join(2)
        self.result['joined'] = not self.thread.is_alive()
        return self.result
