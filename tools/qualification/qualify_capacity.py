"""Run capacity qualification phases while observing both hosts' memory.

Only synthetic workloads from the existing qualification scripts are sent.
Every phase checks the pair's identity; it never restarts or selects a profile.
"""
import argparse
import json
import re
import subprocess
import sys
import threading
import time

from common import ROOT, SOURCE, atomic, containers, now
from cluster import get, memory


def commands(phase, prefix, streams, smoke_prompt_tokens=2048, smoke_reply_tokens=1024):
    if phase == 'native':
        return [('million', 'qualify_native_context.py', ['--tokens', '1048576',
                '--reply-tokens', '256', '--mixed'])]
    if phase == 'draft-tuning':
        return [
            ('baseline', 'qualify.py', ['baseline']),
            ('structured', 'qualify.py', ['structured']),
            ('sampling', 'qualify_sampling.py', ['--mode', 'random']),
            ('ordinary-parity', 'qualify_verify64.py', ['--streams', '16', '24', '32', '32']),
            ('full-sessions', 'qualify_memory.py', ['--streams', str(streams), '--rounds', '2',
                '--initial-tokens', '261120', '--growth', '0', '--reply-tokens', '1024',
                '--shared-prefix', '--identical', '--require-concurrency']),
            ('million', 'qualify_native_context.py', ['--tokens', '1048576',
                '--reply-tokens', '256', '--mixed']),
            ('queue', 'qualify_pool_queue.py', ['--allow-fragmentation']),
            ('recovery', 'qualify_recovery.py', []),
            ('soak', 'qualify_soak.py', ['--seconds', '360', '--streams', str(streams)]),
        ]
    if phase == 'verify64':
        return [
            ('baseline', 'qualify.py', ['baseline']),
            ('structured', 'qualify.py', ['structured']),
            ('sampling', 'qualify_sampling.py', []),
            ('full-sessions', 'qualify_memory.py', ['--streams', str(streams), '--rounds', '2',
                '--initial-tokens', '261120', '--growth', '0', '--reply-tokens', '1024',
                '--shared-prefix', '--identical', '--require-concurrency']),
            ('million', 'qualify_native_context.py', ['--mixed']),
            ('recovery', 'qualify_recovery.py', []),
            ('soak', 'qualify_soak.py', ['--seconds', '300', '--streams', str(streams)]),
        ]
    if phase == 'smoke':
        return [
            ('baseline', 'qualify.py', ['baseline']),
            ('structured', 'qualify.py', ['structured']),
            ('sampling', 'qualify_sampling.py', []),
            ('distinct', 'qualify_pool.py', ['--streams', str(streams), '--prompt-tokens', str(smoke_prompt_tokens),
                                           '--reply-tokens', str(smoke_reply_tokens), '--check-solo']),
            ('ordinary', 'qualify_pool.py', ['--streams', str(streams), '--prompt-tokens', str(smoke_prompt_tokens),
                                           '--reply-tokens', str(smoke_reply_tokens), '--check-solo', '--no-draft']),
        ]
    if phase == 'pressure':
        return [
            ('full-sessions', 'qualify_memory.py', ['--streams', str(streams), '--rounds', '2',
                '--initial-tokens', '261120', '--growth', '0', '--reply-tokens', '1024',
                '--shared-prefix', '--identical', '--require-concurrency']),
            ('tools', 'qualify_memory.py', ['--mode', 'tools', '--streams', str(streams),
                '--rounds', '2', '--initial-tokens', '16384', '--growth', '8192', '--reply-tokens', '256']),
        ]
    return [
        ('million', 'qualify_native_context.py', ['--mixed']),
        ('queue', 'qualify_pool_queue.py', ['--allow-fragmentation']),
        ('recovery', 'qualify_recovery.py', []),
        ('soak', 'qualify_soak.py', ['--seconds', '600', '--streams', str(streams)]),
    ]


def identities():
    result = {}
    for host in ('head', 'worker'):
        rows = containers(host)
        assert len(rows) == 1 and rows[0]['State']['Running'], host + ': expected one running owned rank'
        result[host] = dict(container=rows[0]['Id'], image=rows[0]['Image'])
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--phase', choices=('smoke', 'pressure', 'finish', 'verify64', 'draft-tuning', 'native'), required=True)
    p.add_argument('--record', required=True)
    p.add_argument('--smoke-prompt-tokens',type=int,default=2048)
    p.add_argument('--smoke-reply-tokens',type=int,default=1024)
    args = p.parse_args()
    assert re.fullmatch('[a-z0-9-]+', args.record)
    path = ROOT / ('records/validation-' + args.record + '-' + args.phase + '-phase.json')
    assert not path.exists(), 'Preserve prior evidence; choose a new record prefix.'
    h = get('/health')
    plan = commands(args.phase, args.record, h['streams']['max'],
                    args.smoke_prompt_tokens, args.smoke_reply_tokens)
    for name, _, _ in plan:
        child = ROOT / ('records/validation-' + args.record + '-' + name + '.json')
        assert not child.exists(), 'Preserve earlier child receipt: ' + str(child)
    record = dict(started=now(), parameters=vars(args), health_before=h,
                  hosts=identities(), launch=json.loads((ROOT/'records/launch.json').read_text()),
                  tests=[], samples=[], status='running')
    started = time.monotonic()
    done = threading.Event()
    stage = {'name': 'setup'}

    def observe():
        next_hosts = next_print = 0
        while not done.is_set():
            elapsed = time.monotonic() - started
            sample = dict(seconds=round(elapsed, 2), stage=stage['name'])
            try:
                health = get('/health', timeout=5)
                sample['health'] = {k:health.get(k) for k in ('ok','fatal','streams','progress','memory','requests_running')}
                if elapsed >= next_hosts:
                    sample['available_gib'] = {host:memory(host)['MemAvailable']/2**30 for host in ('head','worker')}
                    next_hosts = elapsed + 10
                if elapsed >= next_print:
                    m = health.get('memory', {})
                    print(stage['name'], round(elapsed), 's', health.get('streams'),
                          'peak_GiB', round(m.get('peak_allocated_bytes', 0)/2**30, 3),
                          'OOMs', m.get('allocation_ooms'), flush=True)
                    next_print = elapsed + 45
            except Exception as exc:
                sample['error'] = type(exc).__name__ + ': ' + str(exc)
            record['samples'].append(sample)
            done.wait(2)

    watcher = threading.Thread(target=observe, daemon=True)
    watcher.start()
    try:
        for name, script, extra in plan:
            stage['name'] = name
            receipt = args.record + '-' + name
            cmd = [sys.executable, '-B', str(__import__('pathlib').Path(__file__).parent/script), *extra, '--record', receipt]
            item = dict(name=name, started=now(), command=cmd, receipt='validation-'+receipt+'.json')
            record['tests'].append(item)
            atomic(path, record)
            result = subprocess.run(cmd, cwd=SOURCE, check=False)
            item.update(finished=now(), returncode=result.returncode)
            if result.returncode:
                raise RuntimeError(name + ' failed; inspect its receipt and logs')
            final = get('/health')
            assert final['ok'] and not final['requests_running']
            assert final['memory']['allocation_ooms'] == 0
            assert final['memory']['allocation_retries'] == h['memory']['allocation_retries']
            assert final['memory']['round_graphs_sealed']
            assert final['memory']['round_graph_captures'] == h['memory']['round_graph_captures']
            assert identities() == record['hosts'], 'pair changed during qualification'
            atomic(path, record)
        record.update(status='passed', health_after=get('/health'))
    except BaseException as exc:
        record.update(status='failed', error=type(exc).__name__+': '+str(exc))
        raise
    finally:
        done.set()
        watcher.join(timeout=30)
        record.update(finished=now(), wall_seconds=round(time.monotonic()-started,3))
        atomic(path, record)


if __name__ == '__main__':
    main()
