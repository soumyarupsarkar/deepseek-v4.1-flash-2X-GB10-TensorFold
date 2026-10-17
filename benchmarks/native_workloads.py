"""Homogeneous short-prompt C1/C32 measurements on an idle native deployment.

Uses the kit's set-b tasks, chat requests and streaming timing. C32 requests
carry the kit's numbered variant suffix. Changes no serving configuration.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import time
import urllib.request

from native_decode import ROOT, now, require, sha


def compact_health(h):
    n, s, c = h['native'], h['scheduler'], h['completed']
    return dict(requests=c['requests'], input_tokens=c['prompt_tokens'],
                output_tokens=s['generation_tokens_total'], running=s['running'],
                waiting=s['waiting'], decoding=n['active_streams'] - n['prefilling_streams'],
                prefilling=n['prefilling_streams'], graph_captures=n['graph_captures'],
                resident_graphs=n['round_graphs'])


def summarize(results, samples, streams):
    start, end = min(r['start_s'] for r in results), max(r['end_s'] for r in results)
    generated = sum(r['output_tokens'] for r in results)
    intervals = []
    for left, right in zip(samples, samples[1:]):
        def eligible(sample):
            h = sample.get('health', {})
            return h.get('decoding') == streams and h.get('prefilling') == 0 and h.get('waiting') == 0
        if not (eligible(left) and eligible(right) and start <= left['at_s'] < right['at_s'] <= end):
            continue
        seconds = right['at_s'] - left['at_s']
        tokens = right['health']['output_tokens'] - left['health']['output_tokens']
        if seconds <= 3 and tokens >= 0:
            intervals.append(dict(seconds=seconds, output_tokens=tokens))
    steady_s = sum(i['seconds'] for i in intervals)
    steady_tokens = sum(i['output_tokens'] for i in intervals)
    return dict(wall_s=end - start, output_tokens=generated,
                aggregate_end_to_end_tps=generated / (end - start),
                c1_content_decode_tps=results[0]['content_decode_tps'] if streams == 1 else None,
                per_request_decode_tps_median=statistics.median(r['content_decode_tps'] for r in results),
                steady_decode_s=steady_s, steady_output_tokens=steady_tokens,
                aggregate_steady_decode_tps=steady_tokens / steady_s if steady_s >= 2 else None,
                eligible_intervals=intervals,
                peak_decoding=max((s.get('health', {}).get('decoding', 0) for s in samples), default=0),
                ttft_s_median=statistics.median(r['ttft_s'] for r in results),
                input_tokens=[r['input_tokens'] for r in results],
                reply_tokens=[r['output_tokens'] for r in results])


def group_results(waves):
    groups = []
    shapes = sorted({(w['streams'], w['temperature'], w['task']) for w in waves if w['phase'] == 'scored'})
    for streams, temperature, task in shapes:
        rows = [w for w in waves if w['phase'] == 'scored' and
                (w['streams'], w['temperature'], w['task']) == (streams, temperature, task)]
        metrics = {}
        for key in ('c1_content_decode_tps', 'aggregate_steady_decode_tps', 'aggregate_end_to_end_tps'):
            values = [w['summary'][key] for w in rows]
            complete = all(v is not None for v in values)
            metrics[key] = dict(all=values, median=statistics.median(values) if complete else None,
                                min=min(values) if complete else None, max=max(values) if complete else None)
        groups.append(dict(streams=streams, temperature=temperature, task=task, repetitions=len(rows),
                           metrics=metrics,
                           output_tokens_per_wave=[w['summary']['output_tokens'] for w in rows],
                           identical_replies_across_repetitions=all(
                               len({w['results'][i]['text_sha256'] for w in rows}) == 1 for i in range(streams))))
    return groups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    source, out = args.source.resolve(), args.out.resolve()
    require(not out.exists() and out.parent.is_dir(), 'Use a new receipt path in an existing directory')
    sys.path.insert(0, str(source / 'deployment/scripts'))
    from configuration import load, profile
    from engine_health import ready
    from runtime import Pair
    sys.path.insert(0, str(ROOT / 'tools/dsv41'))
    import kit_bench as kit

    def git(*argv):
        return subprocess.check_output(['git', *argv], cwd=source, text=True).strip()

    revision = git('rev-parse', 'HEAD')
    require(not git('status', '--porcelain'), 'Serving checkout must be clean')
    pair = Pair(load(source / 'deployment/local.json'))
    pair.ownership()
    launch_path = pair.state / 'launch.json'
    launch = json.loads(launch_path.read_text())
    build = json.loads((pair.state / 'build.json').read_text())
    require(build['revision'] == revision and build['id'] == launch['image'], 'Build/launch/source mismatch')
    require(sha(ROOT / 'tools/dsv41/kit_bench.py') == sha(source / 'tools/dsv41/kit_bench.py'),
            'Benchmark kit differs from serving checkout')
    bind = pair.config['api']['bind']
    base = f"http://{'127.0.0.1' if bind == '0.0.0.0' else bind}:{pair.config['api']['port']}"
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))

    class Client(kit.Client):
        def _req(self, path, body=None, timeout=300):
            return super()._req(path, body, timeout=min(timeout, 300))

        def health(self):
            h = self.get('/health', timeout=15)
            require(ready(h, profile()), 'Server is unhealthy or profile changed')
            require(h['native']['round_graphs'] <= h['native']['graph_limit'], 'Graph budget exceeded')
            return compact_health(h)

        def idle(self, timeout=0):
            deadline = time.monotonic() + timeout
            while True:
                h = self.health()
                if h['running'] == h['waiting'] == 0:
                    return h
                require(time.monotonic() < deadline, 'Other requests are active; run refused')
                time.sleep(.02)

    client = Client(base, 'deepseek-v4.1-flash', None)
    rank_epochs = {}

    def ranks():
        require(json.loads(launch_path.read_text()) == launch, 'Launch changed')
        for host in ('head', 'worker'):
            rows = pair.containers(host)
            require(len(rows) == 1, 'Expected one owned rank')
            row = rows[0]
            require(row['Id'] == launch['containers'][host] and row['Image'] == launch['image'], 'Rank identity mismatch')
            require(row['State']['Running'] and row['RestartCount'] == 0, 'Rank stopped or restarted')
            epoch = (row['Id'], row['State']['StartedAt'])
            require(rank_epochs.get(host, epoch) == epoch, 'Rank epoch changed')
            rank_epochs[host] = epoch
        monitor = pair.monitor_properties()
        require(monitor['ActiveState'] == 'active' and int(monitor['MainPID']) > 0, 'Monitor not running')
        return dict(both_ranks_running=True, rank_restarts=0, monitor_active=True,
                    available_gib={host: pair.memory(host)['MemAvailable'] / 2**30 for host in ('head', 'worker')})

    frozen = {str(p.relative_to(ROOT)): sha(p) for p in
              (Path(__file__), ROOT / 'benchmarks/native_decode.py', ROOT / 'tools/dsv41/kit_bench.py')}
    record = dict(schema_version=1, status='running', started=now(), runtime_source=revision,
                  runtime_image=launch['image'], client_files=frozen,
                  profile_sha256=sha(source / 'deployment/config/profile.json'),
                  protocol=dict(tasks=['code', 'prose', 'counting'], streams=[1, 32], temperatures=[0, 1],
                      repetitions=3, maximum_reply_tokens=384, eos_allowed=True, thinking=False,
                      input_padding=False, c32_variant_suffix=' (variant N), N=0..31',
                      sampling_seeds='42000 + request index, repeated across repetitions',
                      warmup='One unscored wave per shape, 32 output tokens at C1 and 64 at C32',
                      order='Temperature, task, concurrency; warmup then three consecutive repetitions',
                      c1_rate='(output tokens - 1) / first-to-last-content seconds',
                      c32_rate='health-counter output tokens / eligible full-occupancy decode seconds',
                      health_poll_seconds=.25, minimum_steady_seconds=2,
                      end_to_end='all output tokens / earliest request start to latest response end',
                      cache_scope='Warm per shape; no cold-prefix claim'), waves=[])

    def save():
        temp = out.with_name(out.name + '.tmp')
        temp.write_text(json.dumps(record, indent=2) + '\n')
        temp.replace(out)

    def wave(name, prompt, streams, temperature, phase, repetition):
        require(all(sha(ROOT / f) == h for f, h in frozen.items()), 'Benchmark source changed during run')
        before = client.idle()
        cap = 384 if phase == 'scored' else (32 if streams == 1 else 64)
        epoch = time.perf_counter()
        samples, results = [], []
        stop = threading.Event()
        gate = threading.Barrier(streams)
        row = dict(task='counting' if name == 'structured' else name, streams=streams,
                   temperature=temperature, phase=phase, repetition=repetition,
                   maximum_reply_tokens=cap, before=before, results=results, samples=samples)

        def observe():
            while not stop.is_set():
                began = time.perf_counter()
                try:
                    h = client.health()
                    samples.append(dict(at_s=time.perf_counter() - epoch,
                                        probe_s=time.perf_counter() - began, health=h))
                except Exception as exc:
                    samples.append(dict(at_s=time.perf_counter() - epoch, error=type(exc).__name__ + ': ' + str(exc)))
                stop.wait(.25)

        def request(index):
            text = prompt if streams == 1 else prompt + f' (variant {index})'
            body = dict(kit.decode_body(text, cap), temperature=temperature, seed=42000 + index)
            gate.wait(timeout=30)
            result = client.stream(body, '/v1/chat/completions')
            require(type(result['tokens']) is int and 1 < result['tokens'] <= cap, 'Invalid output-token count')
            require(result['decode_tps'] is not None and result['decode_tps'] > 0, 'Missing decode timing')
            return dict(index=index, input_tokens=result['prompt_tokens'], output_tokens=result['tokens'],
                        start_s=result['start'] - epoch, end_s=result['end'] - epoch,
                        ttft_s=result['ttft_s'], first_to_last_content_s=result['decode_s'],
                        content_decode_tps=result['decode_tps'], chunks=result['chunks'],
                        prompt_sha256=hashlib.sha256(text.encode()).hexdigest(),
                        text_sha256=hashlib.sha256(result['text'].encode()).hexdigest())

        watcher = threading.Thread(target=observe, daemon=True)
        watcher.start()
        try:
            with ThreadPoolExecutor(max_workers=streams) as pool:
                futures = [pool.submit(request, i) for i in range(streams)]
                for future in as_completed(futures):
                    results.append(future.result())
            results.sort(key=lambda r: r['index'])
        finally:
            stop.set()
            watcher.join(timeout=20)
            record['waves'].append(row)
            save()
        after = client.idle(timeout=30)
        row['after'] = after
        require(after['requests'] - before['requests'] == streams, 'Request-counter contamination')
        require(after['output_tokens'] - before['output_tokens'] == sum(r['output_tokens'] for r in results),
                'Output-token-counter contamination')
        require(after['input_tokens'] - before['input_tokens'] == sum(r['input_tokens'] for r in results),
                'Input-token-counter contamination')
        require(not any('error' in s for s in samples), 'Health polling failed')
        row['summary'] = summarize(results, samples, streams)
        row['graph_captures'] = after['graph_captures'] - before['graph_captures']
        if phase == 'scored' and streams == 32:
            require(row['summary']['peak_decoding'] == 32, 'C32 occupancy was not observed')
            require(row['summary']['aggregate_steady_decode_tps'] is not None, 'Insufficient C32 steady interval')
        row['status'] = 'passed'
        save()
        print(json.dumps({k: row[k] for k in ('task', 'streams', 'temperature', 'phase', 'repetition')} |
                         {k: row['summary'][k] for k in ('c1_content_decode_tps', 'aggregate_steady_decode_tps',
                                                        'aggregate_end_to_end_tps', 'steady_decode_s', 'output_tokens')}), flush=True)

    with out.open('x') as f:
        f.write(json.dumps(record, indent=2) + '\n')
    deadline = time.monotonic() + 3600
    try:
        record['before'] = ranks()
        record['counters_before'] = client.idle()
        save()
        for temperature in (0, 1):
            for name, prompt in kit.PROMPT_SETS['b']:
                for streams in (1, 32):
                    ranks()
                    for phase, rep in [('warmup', -1)] + [('scored', i) for i in range(3)]:
                        require(time.monotonic() < deadline, 'Campaign time bound exceeded')
                        wave(name, prompt, streams, temperature, phase, rep)
        record['after'] = ranks()
        record['counters_after'] = client.idle()
        require(git('rev-parse', 'HEAD') == revision and not git('status', '--porcelain'), 'Serving source changed')
        require(len(record['waves']) == 48 and all(w['status'] == 'passed' for w in record['waves']), 'Incomplete campaign')
        requests = [r for w in record['waves'] for r in w['results']]
        for key, expected in [('requests', len(requests)), ('output_tokens', sum(r['output_tokens'] for r in requests)),
                              ('input_tokens', sum(r['input_tokens'] for r in requests))]:
            require(record['counters_after'][key] - record['counters_before'][key] == expected,
                    'Traffic between waves contaminated the campaign: ' + key)
        record['groups'] = group_results(record['waves'])
        record['checks'] = dict(owned_rank_identity=True, exact_request_and_token_counters=True,
                               all_scored_c32_waves_reached_full_occupancy=True, all_repetitions_retained=True,
                               no_host_or_server_configuration_changes=True)
        record['status'] = 'passed'
    except BaseException as exc:
        record.update(status='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed',
                      error=type(exc).__name__ + ': ' + str(exc))
        raise
    finally:
        record['finished'] = now()
        save()


if __name__ == '__main__':
    main()
