"""Finite matched busy/idle observations; no restart, endurance or leak-free claim."""
import argparse
import datetime
import json
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time


def signature(health):
    """Compare resident work, not lifetime counters or free-extent placement."""
    assert health['ok'] and not health['requests_running'] and not health.get('busy')
    m = health['memory']
    return dict(snapshot_bytes=m['snapshot_bytes'], prefixes=m['kept_prompts'],
                round_graphs=m['round_graphs'], captures=m['round_graph_captures'],
                reserved_bytes=m['reserved_bytes'],
                pool={k:m['kv_pool'][k] for k in ('allocator_rows', 'retained_reserved_rows',
                      'retained_prefix_tokens', 'active_reserved_rows', 'active_requests')})


def compare(windows, limit_bytes):
    assert len(windows) >= 2, 'At least two matched quiet windows are required'
    assert all(w['signature'] == windows[0]['signature'] for w in windows), 'Quiet cache states differ'
    summaries = []
    for window in windows:
        assert len(window['samples']) >= 6, 'Insufficient fresh quiet observations'
        summaries.append({host:{key:statistics.median(s['hosts'][host][key] for s in window['samples'][-6:])
                         for key in ('glibc_live_bytes', 'rank_anon_plus_swap_bytes', 'available_bytes')}
                         for host in ('head', 'worker')})
    growth = {host:{key:max(s[host][key] for s in summaries[1:])-summaries[0][host][key]
                   for key in ('glibc_live_bytes', 'rank_anon_plus_swap_bytes')}
              for host in ('head', 'worker')}
    return dict(matched=True, window_medians=summaries, maximum_growth_bytes=growth,
                within_budget=all(v <= limit_bytes for row in growth.values() for v in row.values()))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--record', required=True)
    p.add_argument('--cycles', type=int, default=3)
    p.add_argument('--quiet-seconds', type=int, default=120)
    p.add_argument('--streams', type=int, default=8)
    p.add_argument('--tools', type=int, default=16)
    p.add_argument('--max-growth-mib', type=int, default=256,
                   help='Predeclared finite growth gate after warm-up; not a leak diagnosis')
    a = p.parse_args()
    assert re.fullmatch('[a-z0-9-]+', a.record)
    assert 2 <= a.cycles <= 8 and 40 <= a.quiet_seconds <= 600
    assert 1 <= a.streams <= 32 and 1 <= a.tools <= 64 and 0 <= a.max_growth_mib <= 1024
    from common import API_BASE, PAIR, ROOT, atomic, now
    from cluster import get
    from benchmark import evict
    from memory_watch import health_sample
    path = ROOT/('records/validation-'+a.record+'-memory-cycles.json')
    assert not path.exists(), 'Preserve previous attempts'
    before = get('/health')
    signature(before)
    launch = json.loads((PAIR.state/'launch.json').read_text())
    record = dict(status='running', started=now(), parameters=vars(a), windows=[], workloads=[],
                  image=launch['image'], containers=launch['containers'], health_before=health_sample(before),
                  scope='Finite matched-state observations, not endurance or an allocation-level leak diagnosis')
    atomic(path, record)
    try:
        for cycle in range(a.cycles):
            name = a.record+'-busy-'+str(cycle)
            script = Path(__file__).with_name('qualify_schema_churn.py')
            command = [sys.executable, '-B', str(script), '--record', name, '--streams', str(a.streams),
                       '--tools', str(a.tools), '--rounds', '2', '--variant-base', '734200']
            # Repeating the same schemas separates warm cache growth from the
            # fresh-schema stress probe, which remains a separate workload.
            subprocess.run(command, check=True)
            child = ROOT/('records/validation-'+name+'-schema-churn.json')
            assert json.loads(child.read_text())['status'] == 'passed'
            record['workloads'].append(child.name)
            evict(API_BASE, 734200)  # identical final retained-prefix set each cycle
            health = get('/health')
            window = dict(started=now(), signature=signature(health), samples=[])
            record['windows'].append(window)
            counters = (health['requests_total'], health['completion_tokens_total'])
            end = time.monotonic()+a.quiet_seconds
            last_stamp = None
            print('quiet cycle', cycle, 'starting', a.quiet_seconds, 'seconds', flush=True)
            while time.monotonic() < end:
                time.sleep(min(5, max(0, end-time.monotonic())))
                h = get('/health')
                assert signature(h) == window['signature'], 'Quiet state changed'
                assert (h['requests_total'], h['completion_tokens_total']) == counters, 'Unrelated inference during quiet window'
                for key in ('allocation_ooms', 'allocation_retries', 'round_graph_captures'):
                    assert h['memory'][key] == before['memory'][key], key+' changed'
                f = PAIR.state/'memory/samples.jsonl'
                with f.open('rb') as stream:
                    stream.seek(max(0, f.stat().st_size-128*1024))
                    sample = json.loads(stream.read().splitlines()[-1])
                stamp = datetime.datetime.fromisoformat(sample['time'])
                age = (datetime.datetime.now(datetime.timezone.utc)-stamp).total_seconds()
                assert 0 <= age < 30 and sample['failure_count'] == 0, 'Watchdog observation stale or failed'
                if sample['time'] == last_stamp or sample['time'] <= window['started']:
                    continue
                last_stamp = sample['time']
                observation = dict(time=sample['time'], hosts={})
                for host in ('head', 'worker'):
                    row = sample['hosts'][host]
                    heap = row['host_heap']
                    assert not row['errors'] and heap['age_seconds'] < 15
                    assert heap['errors'] == heap['write_errors'] == 0, 'Native observation error'
                    current = heap['current']
                    available = row['meminfo']['MemAvailable']
                    assert available >= sample['minimum_available_bytes'], 'Host floor crossed'
                    observation['hosts'][host] = dict(available_bytes=available,
                        glibc_live_bytes=current['glibc_uordblks']+current['glibc_hblkhd'],
                        rank_anon_plus_swap_bytes=sum(r.get('RssAnon',0)+r.get('VmSwap',0)
                                                     for r in row['rank_processes']),
                        trim_calls=heap['trim_calls'])
                window['samples'].append(observation)
                atomic(path, record)
            window['finished'] = now()
            for host in ('head', 'worker'):
                rows = PAIR.containers(host)
                assert len(rows) == 1 and rows[0]['State']['Running']
                assert rows[0]['Id'] == launch['containers'][host] and rows[0]['Image'] == launch['image']
            atomic(path, record)
        record['comparison'] = compare(record['windows'], a.max_growth_mib*2**20)
        assert record['comparison']['within_budget'], 'Matched quiet growth exceeded the declared budget'
        record.update(status='passed', health_after=health_sample(get('/health')))
    except (KeyboardInterrupt, SystemExit) as exc:
        record.update(status='interrupted', error=type(exc).__name__+': '+str(exc))
        raise
    except BaseException as exc:
        record.update(status='failed', error=type(exc).__name__+': '+str(exc))
        raise
    finally:
        record['finished'] = now()
        atomic(path, record)


if __name__ == '__main__':
    main()
