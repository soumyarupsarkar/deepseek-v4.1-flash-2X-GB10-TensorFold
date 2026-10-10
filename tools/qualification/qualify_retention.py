"""Qualify 32 independent retained prefixes and sequential continuation reuse.

Synthetic raw continuations test cache correctness, not answer quality. No
throughput claim is derived from this client. Existing KV/host floors stay fixed.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time

from common import ROOT, atomic, now
from benchmark import digest, evict, prompt, tokens
from cluster import get, memory
from qualify import BASE, post
from qualify_capacity import identities


def ask(ids):
    r = post(dict(prompt=ids, max_tokens=16, ignore_eos=True,
                  temperature=0, draft=False), '/v1/completions', timeout=3600)
    body = r['response']
    assert body['usage']['prompt_tokens'] == len(ids)
    assert body['usage']['completion_tokens'] == 16
    return dict(seconds=r['seconds'], prompt_sha256=digest(ids),
                usage=body['usage'], tensorfold=body['tensorfold'])


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--record', required=True)
    p.add_argument('--prefix-tokens', type=int, default=16384)
    a = p.parse_args()
    assert a.record.replace('-', '').isalnum()
    path = ROOT/'records'/f'validation-{a.record}.json'
    assert not path.exists(), 'Preserve earlier evidence'
    first = get('/health')
    keep = first['memory']['retention']
    assert keep == dict(enabled=True, max_prefixes=32, checkpoint_policy='recent', checkpoints=2)
    assert first['ok'] and not first['requests_running']
    record = dict(started=now(), status='running', parameters=vars(a),
                  launch=json.loads((ROOT/'records/launch.json').read_text()),
                  hosts=identities(), health_before=first, stages=[], samples=[])
    chunk = int(record['launch']['settings']['environment']['TF_DS_PREFILL_CHUNK'])
    assert chunk > 0 and a.prefix_tokens >= 2*chunk
    record['checkpoint_chunk_tokens'] = chunk
    stop = threading.Event()
    started = time.monotonic()
    def observe():
        while not stop.is_set():
            try:
                h = get('/health', timeout=10)
                record['samples'].append(dict(seconds=time.monotonic()-started,
                    memory=h['memory'], streams=h['streams'], scheduler=h.get('scheduler'),
                    available_gib={host:memory(host)['MemAvailable']/2**30 for host in ('head','worker')}))
            except Exception as exc:
                record['samples'].append(dict(seconds=time.monotonic()-started, error=str(exc)))
            stop.wait(5)
    watcher = threading.Thread(target=observe, daemon=True)
    watcher.start()
    def stage(name, results):
        h = get('/health')
        assert h['ok'] and not h['requests_running']
        assert h['memory']['kept_prompts'] == 32
        assert h['memory']['snapshot_references'] <= 64
        record['stages'].append(dict(name=name, results=results, health=h))
        atomic(path, record)
        print(name, 'passed;', h['memory']['snapshot_bytes'], 'snapshot bytes;',
              h['memory']['kv_pool']['resident_logical_tokens'], 'resident tokens', flush=True)
    try:
        evict(BASE, 84000)
        ids = [prompt(BASE, a.prefix_tokens, 74000+i, 'code')[0] for i in range(32)]
        with ThreadPoolExecutor(max_workers=32) as pool:
            cold = list(pool.map(ask, ids))
        assert all(r['tensorfold']['cached'] == 0 for r in cold)
        stage('32-distinct-cold-prefixes', cold)
        # Sequential revisits expose LRU churn that a simultaneous admission
        # wave could hide. Every conversation must still be available.
        warm = [ask(item) for item in ids]
        # Revisit must resume at a recent complete boundary before the replay
        # tail. A 2K chunk cannot promise the old 1K maximum refill distance.
        assert all(r['tensorfold']['cached'] >= a.prefix_tokens-max(1024, chunk) for r in warm)
        assert [r['tensorfold']['token_sha'] for r in warm] == [r['tensorfold']['token_sha'] for r in cold]
        stage('32-sequential-revisits', warm)
        suffix = tokens(BASE, text=' Continue with another small example and explanation. ')
        suffix = (suffix*((512+len(suffix)-1)//len(suffix)))[:512]
        continued = [item+suffix for item in ids]
        replies = [ask(item) for item in continued]
        assert all(r['tensorfold']['cached'] >= a.prefix_tokens for r in replies)
        stage('32-sequential-extensions', replies)
        again = [ask(item) for item in continued]
        assert all(r['tensorfold']['cached'] >= a.prefix_tokens for r in again)
        assert [r['tensorfold']['token_sha'] for r in again] == [r['tensorfold']['token_sha'] for r in replies]
        stage('32-extended-prefix-revisits', again)
        # Refresh entry zero, then introduce an unrelated thirty-third prefix.
        refreshed = ask(continued[0])
        extra = ask(prompt(BASE,a.prefix_tokens,99999,'code')[0])
        still_hot = ask(continued[0])
        evicted = ask(continued[1])
        assert refreshed['tensorfold']['cached'] > 0 and still_hot['tensorfold']['cached'] > 0
        assert extra['tensorfold']['cached'] == evicted['tensorfold']['cached'] == 0
        stage('least-recently-used-eviction', [refreshed,extra,still_hot,evicted])
        final = get('/health')
        for key in ('allocation_ooms','allocation_retries','round_graph_captures'):
            assert final['memory'][key] == first['memory'][key], key
        assert identities() == record['hosts']
        for sample in record['samples']:
            if 'available_gib' in sample:
                assert min(sample['available_gib'].values()) >= 2, sample
        record.update(status='passed', health_after=final)
    except BaseException as exc:
        record.update(status='failed', error=type(exc).__name__+': '+str(exc))
        raise
    finally:
        stop.set()
        watcher.join(timeout=15)
        record.update(finished=now(), seconds=time.monotonic()-started)
        atomic(path, record)
    print('32-prefix retention, sequential reuse, parity and eviction passed', flush=True)


if __name__ == '__main__':
    main()
