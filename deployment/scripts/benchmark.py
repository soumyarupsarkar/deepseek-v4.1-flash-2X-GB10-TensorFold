"""Reproducible streaming waves; honest cold/warm and wall/steady timing receipts.

Standard library only. Uses the retained upstream set-b prompts and word corpus.
No benchmark knobs are exposed by the production API. Each suite is an explicit
JSON list of cases: streams, prompt_tokens (0 means short set-b chat), reply_tokens,
mode (default/ordinary), cache (cold/shared), temperature, seed, prompt_class.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys
import threading
import time
import urllib.request

from configuration import SOURCE, STATE as ROOT
from runtime import atomic, now

sys.path.insert(0, str(SOURCE / 'tools/dsv41'))
from kit_bench import PROMPT_SETS, WORDS

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
MODEL = 'DeepSeek-V4.1-Flash-Keys'
EVICTION_TOKENS = 4096
EVICTION_PROTOCOL = 'retained-prefix-lru-4096-v2'


def validate_cases(cases, *, parallel=None, context=None):
    """Reject malformed workloads before evicting prefixes or restarting ranks."""
    if not isinstance(cases, list) or not cases:
        raise ValueError('Benchmark suite must contain at least one case')
    classes = set(dict(PROMPT_SETS['b'])) | {'mixed'}
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f'Case {index} must be an object')
        for field, minimum in (('streams',1),('prompt_tokens',0),('reply_tokens',1)):
            value = case.get(field)
            if type(value) is not int or value < minimum:
                raise ValueError(f'Case {index}: invalid {field}')
        if case.get('prompt_class','mixed') not in classes:
            raise ValueError(f'Case {index}: unknown prompt_class; expected {sorted(classes)}')
        if case.get('mode','default') not in ('default','ordinary'):
            raise ValueError(f'Case {index}: unknown mode')
        if case.get('cache','cold') not in ('cold','shared'):
            raise ValueError(f'Case {index}: unknown cache policy')
        temperature = case.get('temperature',0)
        if (type(temperature) not in (int,float) or not math.isfinite(temperature)
                or temperature < 0 or type(case.get('seed',42000)) is not int):
            raise ValueError(f'Case {index}: invalid sampling settings')
        if parallel is not None and case['streams'] > parallel:
            raise ValueError(f'Case {index}: streams exceed profile capacity')
        if context is not None and case['prompt_tokens']+case['reply_tokens'] > context:
            raise ValueError(f'Case {index}: token budget exceeds profile context')


def digest(value):
    return hashlib.sha256(json.dumps(value, separators=(',', ':')).encode()).hexdigest()


def percentile(values, q):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    x = (len(values) - 1) * q
    i = int(x)
    return values[i] + (values[min(i + 1, len(values) - 1)] - values[i]) * (x - i)


def request(base, path, body=None, timeout=3600):
    raw = json.dumps(body, separators=(',', ':')).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=raw, headers={'Content-Type': 'application/json'})
    return OPENER.open(req, timeout=timeout)


def json_request(base, path, body=None, timeout=3600):
    with request(base, path, body, timeout) as response:
        return json.load(response)


def sampled_health(health):
    """Static capacity and cumulative calibration tables live in before/after.

    Poll receipts retain only changing gauges/counters, so long-context tests
    do not serialize the same profile and large calibration table every second.
    """
    keys = ('ok', 'requests_running', 'requests_total', 'completion_tokens_total',
            'streams', 'scheduler', 'progress')
    out = {k: health[k] for k in keys if k in health}
    keys = ('allocated_bytes', 'reserved_bytes', 'peak_allocated_bytes', 'allocation_retries',
            'allocation_ooms', 'snapshot_bytes', 'kept_prompts', 'round_graphs',
            'round_graph_captures', 'drafter_cuda_graphs', 'kv_pool')
    out['memory'] = {k: health['memory'][k] for k in keys if k in health.get('memory', {})}
    return out


def tokens(base, text=None, messages=None):
    body = dict(model=MODEL, add_special_tokens=False)
    if messages is not None:
        body.update(messages=messages, add_generation_prompt=True,
                    chat_template_kwargs={'enable_thinking': False})
    else:
        body['prompt'] = text
    return json_request(base, '/tokenize', body)['tokens']


def prompt(base, length, seed, prompt_class='mixed', variant=0):
    """Fixed complete chat suffix; random-word body is synthetic, never a quality benchmark."""
    choices = dict(PROMPT_SETS['b'])
    name = list(choices)[variant % len(choices)] if prompt_class == 'mixed' else prompt_class
    instruction = choices[name]
    if not length:
        text = instruction if variant == 0 else instruction + f' (variant {variant})'
        ids = tokens(base, messages=[{'role': 'user', 'content': text}])
        return ids, name
    rng = random.Random(seed)
    marker = 'REFERENCE_BODY_SENTINEL'
    rendered = tokens(base, messages=[{'role': 'user', 'content': marker + '\n\n' + instruction}])
    marker_ids = tokens(base, text=marker)
    at = next((i for i in range(len(rendered)) if rendered[i:i+len(marker_ids)] == marker_ids), None)
    if at is None:
        raise RuntimeError('Unable to locate the synthetic body in the rendered chat template')
    prefix, suffix = rendered[:at], rendered[at+len(marker_ids):]
    salt = 'Reference ' + ' '.join(str(rng.randrange(10**9)) for _ in range(8)) + '\n'
    salt_ids = tokens(base, text=salt)
    # A bounded seeded word block keeps client memory modest even at one million.
    block = tokens(base, text=' '.join(rng.choice(WORDS) for _ in range(8192)) + '\n')
    need = length - len(prefix) - len(salt_ids) - len(suffix)
    if need < 1:
        raise ValueError('Requested prompt is too short for the complete chat template')
    return prefix + salt_ids + (block * ((need + len(block)-1)//len(block)))[:need] + suffix, name


def evict(base, epoch):
    """Displace the configured prefix cache; measured cold waves verify zero hits."""
    retention = json_request(base, '/health')['memory'].get('retention', {})
    keep = retention.get('max_prefixes', 8) if retention.get('enabled', True) else 0
    for i in range(keep):
        # A sub-chunk prompt produces no retained checkpoint. 4K covers two
        # boundaries even with the largest tested 2K chunk, on every profile.
        ids, _ = prompt(base, EVICTION_TOKENS, 9000000 + epoch*max(keep, 1) + i)
        json_request(base, '/v1/completions', dict(model=MODEL, prompt=ids, max_tokens=1,
                                                temperature=0, draft=False))
    if keep:
        memory = json_request(base, '/health')['memory']
        assert memory['kept_prompts'] == keep, 'Eviction fixtures were not retained'
        assert memory['kv_pool']['retained_prefix_tokens'] == keep*EVICTION_TOKENS, \
            'Eviction left other prefixes or did not create complete checkpoints'
    return dict(protocol=EVICTION_PROTOCOL, prefixes=keep, tokens_per_prefix=EVICTION_TOKENS)


def stream_request(base, body, shared_prompt=None):
    fields = dict(model=MODEL, stream=True, stream_options={'include_usage': True}, **body)
    headers = {'Content-Type': 'application/json'}
    if shared_prompt is None:
        data = json.dumps(fields, separators=(',', ':')).encode()
    else:
        # urllib/http.client accepts an iterable body with an explicit length.
        # All concurrent shared-prefix requests reference the same immutable
        # prompt bytes, rather than retaining 32 full JSON copies on the head.
        fields.pop('prompt')
        metadata = json.dumps(fields, separators=(',', ':')).encode()
        data = (b'{"prompt":', shared_prompt, b','+metadata[1:])
        headers['Content-Length'] = str(sum(map(len, data)))
    return urllib.request.Request(base+'/v1/completions', data=data, headers=headers)


def stream(base, body, gate, index, shared_prompt=None):
    # Serialize before the barrier so large request serialization is not server latency.
    req = stream_request(base, body, shared_prompt)
    gate.wait(timeout=180)
    started = time.perf_counter()
    first = last = None
    usage, stats, finish = {}, {}, None
    text_hash = hashlib.sha256()
    chunks = 0
    with OPENER.open(req, timeout=7200) as response:
        for raw in response:
            if not raw.startswith(b'data:'):
                continue
            raw = raw[5:].strip()
            if raw == b'[DONE]':
                break
            chunk = json.loads(raw)
            if 'error' in chunk:
                raise RuntimeError(str(chunk['error']))
            usage = chunk.get('usage') or usage
            stats.update(chunk.get('tensorfold') or {})
            for choice in chunk.get('choices', []):
                piece = choice.get('text') or (choice.get('delta') or {}).get('content') or ''
                if piece:
                    last = time.perf_counter()
                    first = last if first is None else first
                    chunks += 1
                    text_hash.update(piece.encode())
                finish = choice.get('finish_reason') or finish
    ended = time.perf_counter()
    if not usage:
        raise RuntimeError('Stream ended without usage; refusing a guessed token count')
    count = usage['completion_tokens']
    span = last-first if first is not None else None
    return dict(index=index, start=started, end=ended, wall_s=ended-started,
                first_content=first, last_content=last, ttft_s=first-started if first else None,
                decode_content_span_s=span,
                decode_tps=(count-1)/span if span and span > 0 and count > 1 else None,
                server_decode_tps=(count-1)/stats['decode_s'] if stats.get('decode_s') and count > 1 else None,
                usage=usage, tensorfold=stats, finish=finish, chunks=chunks, text_sha256=text_hash.hexdigest())


def summarize(results, samples, concurrency):
    start, end = min(r['start'] for r in results), max(r['end'] for r in results)
    generated = sum(r['usage']['completion_tokens'] for r in results)
    intervals = []
    for a, b in zip(samples, samples[1:]):
        def eligible(s):
            h = s.get('health', {})
            return (h.get('streams', {}).get('decoding') == concurrency
                    and h.get('streams', {}).get('prefilling') == 0
                    and h.get('scheduler', {}).get('queued', 0) == 0)
        if eligible(a) and eligible(b) and start <= a['at'] < b['at'] <= end:
            dt = b['at'] - a['at']
            dn = b['health']['completion_tokens_total'] - a['health']['completion_tokens_total']
            if dt <= 3 and dn >= 0:
                intervals.append((dt, dn))
    seconds = sum(t for t, _ in intervals)
    total = sum(n for _, n in intervals)
    uncached = sum(r['usage']['prompt_tokens'] - r['tensorfold'].get('cached', 0) for r in results)
    prefill_s = sum(r['tensorfold'].get('prefill_s', 0) for r in results)
    return dict(wall_s=end-start, output_tokens=generated, aggregate_e2e_tps=generated/(end-start),
                requests_per_second=len(results)/(end-start),
                decode_tps_p50=percentile([r['decode_tps'] for r in results], .5),
                decode_tps_p05=percentile([r['decode_tps'] for r in results], .05),
                ttft_s_p50=percentile([r['ttft_s'] for r in results], .5),
                ttft_s_p95=percentile([r['ttft_s'] for r in results], .95),
                latency_s_p95=percentile([r['wall_s'] for r in results], .95),
                uncached_prompt_tokens=uncached,
                engine_prefill_tps=uncached/prefill_s if prefill_s else None,
                effective_prefill_tps=(uncached/results[0]['ttft_s']
                                      if len(results) == 1 and results[0]['ttft_s'] else None),
                sampled_steady_decode_s=seconds, sampled_steady_output_tokens=total,
                sampled_steady_decode_tps=total/seconds if seconds >= 2 else None,
                peak_decoding=max((s.get('health', {}).get('streams', {}).get('decoding', 0) for s in samples), default=0),
                peak_prefilling=max((s.get('health', {}).get('streams', {}).get('prefilling', 0) for s in samples), default=0),
                cached_tokens=sum(r['tensorfold'].get('cached', 0) for r in results),
                drafted=sum(r['tensorfold'].get('drafted', 0) for r in results),
                accepted=sum(r['tensorfold'].get('accepted', 0) for r in results))


def wave(base, case, epoch):
    n = case['streams']
    seed = case.get('seed', 42000)
    eviction = evict(base, epoch) if case.get('cache', 'cold') == 'cold' else None
    shared = case.get('cache') == 'shared'
    ids = [prompt(base, case['prompt_tokens'], seed if shared else seed+i,
                  case.get('prompt_class', 'mixed'), 0 if shared else i) for i in range(1 if shared else n)]
    priming = None
    if shared:
        began = time.perf_counter()
        prime = json_request(base, '/v1/completions', dict(model=MODEL, prompt=ids[0][0], max_tokens=1,
                                                        temperature=0, draft=False), timeout=7200)
        priming = dict(wall_s=time.perf_counter()-began, usage=prime['usage'], tensorfold=prime.get('tensorfold'))
        ids *= n
    before = json_request(base, '/health', timeout=30)
    if before['requests_running']:
        raise RuntimeError('Other requests are active; refusing a contaminated benchmark')
    bodies = [dict(prompt=p, max_tokens=case['reply_tokens'], ignore_eos=True,
                   temperature=case.get('temperature', 0), seed=seed+i,
                   **({'draft': False} if case.get('mode') == 'ordinary' else {})) for i, (p, _) in enumerate(ids)]
    shared_prompt = json.dumps(ids[0][0], separators=(',', ':')).encode() if shared else None
    samples, stop = [], threading.Event()
    def observe():
        while not stop.is_set():
            try:
                t = time.perf_counter()
                health = json_request(base, '/health', timeout=10)
                mem = next(int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines()
                           if line.startswith('MemAvailable:'))
                rss = next(int(line.split()[1])*1024 for line in Path('/proc/self/status').read_text().splitlines()
                           if line.startswith('VmRSS:'))
                samples.append(dict(at=time.perf_counter(), probe_s=time.perf_counter()-t,
                                    health=sampled_health(health), head_available_bytes=mem, client_rss_bytes=rss))
            except Exception as exc:
                samples.append(dict(at=time.perf_counter(), error=str(exc)))
            stop.wait(1)
    watcher = threading.Thread(target=observe, daemon=True)
    watcher.start()
    gate = threading.Barrier(n)
    try:
        with ThreadPoolExecutor(max_workers=n) as pool:
            futures = [pool.submit(stream, base, body, gate, i, shared_prompt) for i, body in enumerate(bodies)]
            results = [f.result() for f in futures]
    except BaseException as exc:
        # Preserve the failing wave too; it is diagnostic evidence, never a
        # successful timing row. The executor has drained before this handler.
        exc.benchmark_wave = dict(case=case, priming=priming, eviction=eviction, health_before=before,
            samples=samples, partial_results=[f.result() for f in locals().get('futures', [])
                                             if f.done() and not f.cancelled() and f.exception() is None])
        raise
    finally:
        stop.set()
        watcher.join(timeout=15)
    try:
        after = json_request(base, '/health', timeout=30)
        assert after['requests_total']-before['requests_total'] == n, 'Other completed requests contaminated the wave'
        assert after['completion_tokens_total']-before['completion_tokens_total'] == sum(
            r['usage']['completion_tokens'] for r in results), 'Token counters include another workload'
        for r, (p, name) in zip(results, ids):
            r.update(prompt_sha256=digest(p), prompt_class=name)
            assert r['usage']['prompt_tokens'] == len(p)
            assert r['usage']['completion_tokens'] == case['reply_tokens'], r
            if case.get('cache', 'cold') == 'cold':
                assert r['tensorfold']['cached'] == 0, 'Cold benchmark reused prefix tokens'
        assert after['ok'] and not after['requests_running']
        for key in ('allocation_ooms', 'allocation_retries', 'round_graph_captures'):
            assert after['memory'][key] == before['memory'][key], (key, before['memory'][key], after['memory'][key])
        for observed in [before, after] + [s['health'] for s in samples if 'health' in s]:
            pool = observed.get('memory', {}).get('kv_pool')
            if pool:
                assert pool['reserved_rows'] == pool['reserved_accounted_rows'], pool
                assert 0 <= pool['resident_logical_tokens'] <= pool['reserved_rows'] <= pool['allocator_rows'], pool
                assert pool['free_rows'] + pool['reserved_rows'] == pool['allocator_rows'], pool
        return dict(case=case, priming=priming, eviction=eviction, health_before=before, health_after=after, results=results,
                    summary=summarize(results, samples, n), samples=samples)
    except BaseException as exc:
        # Post-response cache/counter checks can fail after every request has
        # completed. Keep those outputs and samples too, without scoring them.
        exc.benchmark_wave = dict(case=case, priming=priming, eviction=eviction,
            health_before=before, health_after=locals().get('after'),
            samples=samples, results=results)
        raise



def main():
    p = argparse.ArgumentParser()
    p.add_argument('--suite', type=Path, required=True)
    p.add_argument('--record', required=True)
    p.add_argument('--base', default='http://127.0.0.1:8000')
    p.add_argument('--warmup', action='store_true', help='Run and separately retain a fixed unscored warm-up')
    a = p.parse_args()
    if not a.record.replace('-', '').isalnum():
        raise ValueError('Use a simple alphanumeric record name')
    cases = json.loads(a.suite.read_text())
    validate_cases(cases)
    script = Path(__file__).read_bytes()
    script_sha = hashlib.sha256(script).hexdigest()
    archive = ROOT / 'records/benchmark-clients' / (script_sha + '.py')
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        archive.write_bytes(script)
    fixtures = (SOURCE/'tools/dsv41/kit_bench.py').read_bytes()
    fixture_sha = hashlib.sha256(fixtures).hexdigest()
    fixture_archive = archive.parent / ('kit-'+fixture_sha+'.py')
    if not fixture_archive.exists():
        fixture_archive.write_bytes(fixtures)
    path = ROOT / 'records' / ('benchmark-'+a.record+'.json')
    if path.exists():
        raise RuntimeError('Preserve existing receipts; choose another record name')
    value = dict(started=now(), contract_version=4, cases=cases, cases_sha256=digest(cases),
                 launch=json.loads((ROOT/'launch.json').read_text()),
                 script_sha256=script_sha, fixture_sha256=fixture_sha, rows=[], status='running',
                 eviction_protocol=EVICTION_PROTOCOL,
                 warmup_protocol='code-prose-c8-v2' if a.warmup else 'none', warmup=[])
    atomic(path, value)
    try:
        if a.warmup:
            for j, (streams, length, count, kind) in enumerate(
                    ((1,0,384,'code'),(1,0,384,'prose'),(8,1024,128,'mixed'))):
                case = dict(streams=streams,prompt_tokens=length,reply_tokens=count,
                            prompt_class=kind,cache='cold',mode='default',temperature=0,seed=43000)
                value['warmup'].append(wave(a.base,case,100000+j))
                atomic(path,value)
                print('Unscored warm-up',j,'passed',flush=True)
        for i, case in enumerate(cases):
            row = wave(a.base, case, i)
            value['rows'].append(row)
            atomic(path, value)
            summary = row['summary']
            print(json.dumps(dict(case_index=i, streams=case['streams'], prompt=case['prompt_tokens'],
                  mode=case.get('mode'), cache=case.get('cache'), wall_s=round(summary['wall_s'], 3),
                  aggregate_e2e_tps=round(summary['aggregate_e2e_tps'], 3),
                  steady_decode_tps=summary['sampled_steady_decode_tps'],
                  effective_prefill_tps=summary['effective_prefill_tps'],
                  peak_decoding=summary['peak_decoding'])), flush=True)
        value['status'] = 'passed'
    except BaseException as exc:
        value.update(status='failed', error=type(exc).__name__+': '+str(exc))
        if hasattr(exc, 'benchmark_wave'):
            value['failed_wave'] = exc.benchmark_wave
        raise
    finally:
        value['finished'] = now()
        atomic(path, value)


if __name__ == '__main__':
    main()
