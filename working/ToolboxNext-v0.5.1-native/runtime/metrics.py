"""Read-only /proc sampling; no D-Bus, shell or network control."""
import os
import time


def read(path):
    with open(path, 'r', encoding='utf-8', errors='replace') as handle:
        return handle.read(1048576)


def parse_cpu(text):
    values = [int(v) for v in text.splitlines()[0].split()[1:9]]
    return sum(values), values[3] + (values[4] if len(values)>4 else 0)


def cpu_percent(before, after):
    total, idle = after[0]-before[0], after[1]-before[1]
    return round(100.0*(total-idle)/total, 1) if total>0 and 0<=idle<=total else None


def parse_memory(text):
    values = {}
    for line in text.splitlines():
        k, v = line.split(':', 1)
        values[k] = int(v.split()[0])*1024
    total = values.get('MemTotal', 0)
    available = values.get('MemAvailable')
    return {'total':total, 'available':available, 'used':None if available is None else max(0,total-available)}


def parse_network(text):
    rows = {}
    for line in text.splitlines()[2:]:
        name, values = line.split(':', 1)
        parts = values.split()
        rows[name.strip()] = (int(parts[0]), int(parts[8]))
    return rows


class Sampler:
    def __init__(self, storage, proc='/proc', clock=time.monotonic):
        self.storage, self.proc, self.clock = storage, proc, clock
        self.previous = None
        self.history = []

    def sample(self):
        now = self.clock()
        result = {'epoch':time.time(), 'monotonic':now, 'cpu_percent':None,
                  'memory':{}, 'storage':{}, 'networks':[], 'uptime':None, 'errors':[]}
        cpu, net = None, {}
        for field, name, parser in (('cpu','stat',parse_cpu), ('memory','meminfo',parse_memory),
                                    ('network','net/dev',parse_network), ('uptime','uptime',lambda s:float(s.split()[0]))):
            try:
                value = parser(read(os.path.join(self.proc,name)))
                if field == 'cpu': cpu = value
                elif field == 'network': net = value
                else: result[field] = value
            except (OSError, ValueError, IndexError):
                result['errors'].append(field+' unavailable')
        previous = self.previous
        if previous and cpu and previous[1]:
            result['cpu_percent'] = cpu_percent(previous[1], cpu)
        for name in sorted(net,key=lambda n:(not n.startswith(('wlan','wl','eth','en')),n=='lo',n)):
            rate = [None,None]
            if previous and name in previous[2] and now > previous[0]:
                delta = [net[name][i]-previous[2][name][i] for i in (0,1)]
                rate = [round(x/(now-previous[0]),1) if x>=0 else None for x in delta]
            result['networks'].append({'name':name,'rx_bytes':net[name][0], 'tx_bytes':net[name][1],
                                       'rx_per_second':rate[0], 'tx_per_second':rate[1]})
        try:
            fs = os.statvfs(self.storage)
            result['storage'] = {'total':fs.f_blocks*fs.f_frsize, 'available':fs.f_bavail*fs.f_frsize}
        except (AttributeError, OSError):
            import shutil
            total, used, free = shutil.disk_usage(self.storage)
            result['storage'] = {'total':total, 'available':free}
        self.previous = (now,cpu,net)
        self.history.append(result)
        self.history = self.history[-300:]
        return result

    def processes(self):
        rows = []
        try: names = os.listdir(self.proc)
        except OSError: return rows
        for pid in names:
            if not pid.isdigit(): continue
            try:
                text = read(os.path.join(self.proc,pid,'stat'))
                start, end = text.index('('), text.rindex(')')
                fields = text[end+2:].split()
                rows.append({'pid':int(pid), 'name':text[start+1:end][:80], 'state':fields[0],
                             'rss_bytes':max(0,int(fields[21]))*os.sysconf('SC_PAGE_SIZE')})
            except (OSError, ValueError, IndexError): continue
            if len(rows)>=512: break
        return sorted(rows, key=lambda p:p['rss_bytes'], reverse=True)
