"""Bounded, read-only Linux memory sample. Never read argv, environ or requests.

The controller sends this standard-library module over SSH; no host installation
is required. RSS sums include shared mappings and are not physical-memory totals.
"""
import argparse
import json
from pathlib import Path
import time


MEM_FIELDS = ('MemTotal', 'MemAvailable', 'MemFree', 'Buffers', 'Cached',
              'SwapTotal', 'SwapFree', 'AnonPages', 'Mapped', 'Shmem', 'Slab',
              'SReclaimable', 'SUnreclaim', 'KernelStack', 'PageTables', 'Unevictable')
STATUS_FIELDS = ('VmRSS', 'RssAnon', 'RssFile', 'RssShmem', 'VmSwap', 'VmPTE', 'VmHWM')
CGROUP_FIELDS = ('anon', 'file', 'kernel', 'kernel_stack', 'pagetables', 'sock',
                 'shmem', 'file_mapped', 'slab_reclaimable', 'slab_unreclaimable')


def key_values(path, *, colon=False):
    values = {}
    for line in path.read_text().splitlines():
        parts = line.replace(':', '', 1).split() if colon else line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            values[parts[0]] = int(parts[1]) * (1024 if parts[2:] == ['kB'] else 1)
    return values


def pressure(path):
    result = {}
    for line in path.read_text().splitlines():
        parts = line.split()
        result[parts[0]] = {k: float(v) if k != 'total' else int(v)
                            for k, v in (item.split('=') for item in parts[1:])}
    return result


def collect(init_pid=0, *, detail=False, warning_bytes=3*2**30,
            proc=Path('/proc'), cgroups=Path('/sys/fs/cgroup')):
    started = time.monotonic()
    mem = key_values(proc/'meminfo', colon=True)
    if 'MemAvailable' not in mem:
        raise ValueError('MemAvailable absent')
    result = dict(meminfo={k: mem[k] for k in MEM_FIELDS if k in mem},
                  rank_init_pid=init_pid, errors=[])
    detail = detail or mem['MemAvailable'] < warning_bytes
    try:
        result['pressure'] = pressure(proc/'pressure/memory')
    except (OSError, ValueError):
        result['errors'].append('pressure_unavailable')
    try:
        vm = key_values(proc/'vmstat')
        result['vmstat'] = {k: vm[k] for k in ('pgmajfault', 'pswpin', 'pswpout', 'oom_kill') if k in vm}
    except OSError:
        result['errors'].append('vmstat_unavailable')
    processes = {}
    # Both the scan and the emitted process lists have explicit bounds.
    scanned = 0
    for path in proc.iterdir():
        if not path.name.isdigit():
            continue
        if scanned >= 8192 or time.monotonic()-started > 2:
            result['errors'].append('process_scan_truncated')
            break
        scanned += 1
        try:
            rows = dict(line.split(':', 1) for line in (path/'status').read_text().splitlines())
            numbers = key_values(path/'status', colon=True)
            stat = (path/'stat').read_text()
            tail = stat[stat.rfind(')')+2:].split()
            p = dict(pid=int(path.name), ppid=int(rows['PPid']),
                     name=rows['Name'].strip()[:32], uid=int(rows['Uid'].split()[0]),
                     start_ticks=int(tail[19]), threads=int(rows['Threads']),
                     **{k: numbers.get(k, 0) for k in STATUS_FIELDS})
            processes[p['pid']] = p
        except (OSError, ValueError, KeyError, IndexError):
            continue  # Processes can exit while /proc is being sampled.
    members = {init_pid} if init_pid in processes else set()
    while True:
        found = {pid for pid, row in processes.items() if row['ppid'] in members}
        if found <= members:
            break
        members |= found
    ranked = sorted(processes.values(), key=lambda row: row['VmRSS'], reverse=True)
    result['processes_scanned'] = scanned
    result['top_processes'] = ranked[:12]
    result['rank_processes'] = [row for row in ranked if row['pid'] in members][:32]
    result['rank_process_count'] = len(members)
    result['rank_rss_sum_bytes'] = sum(processes[pid]['VmRSS'] for pid in members)
    if init_pid and init_pid not in processes:
        result['errors'].append('rank_init_not_observed')
    if detail:
        chosen = (result['rank_processes'][:4]
                  + [p for p in ranked if p['pid'] not in members][:4])
        details = []
        for row in chosen:
            if time.monotonic()-started > 3:
                result['errors'].append('detail_scan_truncated')
                break
            try:
                smaps = key_values(proc/str(row['pid'])/'smaps_rollup', colon=True)
                details.append(dict(pid=row['pid'], start_ticks=row['start_ticks'],
                                    **{k: smaps[k] for k in ('Rss', 'Pss', 'Pss_Anon', 'Pss_File',
                                       'Pss_Shmem', 'Private_Dirty', 'Swap', 'SwapPss') if k in smaps}))
            except (OSError, ValueError):
                continue
        result['process_details'] = details
    if init_pid:
        try:
            line = next(row for row in (proc/str(init_pid)/'cgroup').read_text().splitlines()
                        if row.startswith('0::'))
            rel = Path(line[3:].lstrip('/'))
            if '..' in rel.parts:
                raise ValueError('Invalid cgroup path')
            cg = cgroups/rel
            values = {}
            for name in ('memory.current', 'memory.peak', 'memory.swap.current'):
                try:
                    values[name] = int((cg/name).read_text())
                except (OSError, ValueError):
                    pass
            for name in ('memory.events', 'memory.stat'):
                try:
                    v = key_values(cg/name)
                    values[name] = {k: n for k, n in v.items() if name == 'memory.events' or k in CGROUP_FIELDS}
                except OSError:
                    pass
            result['cgroup'] = values
        except (OSError, ValueError, StopIteration):
            result['errors'].append('cgroup_unavailable')
    result['collection_seconds'] = round(time.monotonic()-started, 4)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--pid', type=int, default=0)
    parser.add_argument('--warning-bytes', type=int, default=3*2**30)
    parser.add_argument('--detail', action='store_true')
    args = parser.parse_args()
    print(json.dumps(collect(args.pid, detail=args.detail, warning_bytes=args.warning_bytes),
                     separators=(',', ':')))
