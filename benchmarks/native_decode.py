"""Run the unchanged set-b C1 kit against an idle, owned native deployment.

Checks rank identity and request/token counters without restarting ranks or
changing configuration. Receipts contain timings and hashes, not output text.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
from types import SimpleNamespace
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True,
                        help='Clean, pinned checkout owning the running deployment')
    parser.add_argument('--out', type=Path, required=True, help='New receipt path')
    args = parser.parse_args()
    source = args.source.resolve()
    out = args.out.resolve()
    require(not out.exists(), 'Preserve previous receipts; choose a new output path')
    require(out.parent.is_dir(), 'Create the receipt directory first')

    sys.path.insert(0, str(source / 'deployment/scripts'))
    from configuration import load, profile
    from runtime import Pair
    from engine_health import ready
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
    require(build['revision'] == revision and build['id'] == launch['image'],
            'Source, build and launch identities differ')
    require(sha(ROOT / 'tools/dsv41/kit_bench.py') == sha(source / 'tools/dsv41/kit_bench.py'),
            'Benchmark kit differs from the serving checkout')
    base = f"http://127.0.0.1:{pair.config['api']['port']}"
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
    observed_ranks = {}

    def ranks():
        require(json.loads(launch_path.read_text()) == launch, 'Launch changed')
        for host in ('head', 'worker'):
            rows = pair.containers(host)
            require(len(rows) == 1, 'Expected one owned rank per host')
            row = rows[0]
            require(row['Id'] == launch['containers'][host] and row['Image'] == launch['image'],
                    'Running rank identity differs from launch')
            require(row['State']['Running'] and row['RestartCount'] == 0, 'Rank stopped or restarted')
            identity = (row['Id'], row['State']['StartedAt'])
            require(observed_ranks.get(host, identity) == identity, 'Rank epoch changed')
            observed_ranks[host] = identity
        monitor = pair.monitor_properties()
        require(monitor['ActiveState'] == 'active' and int(monitor['MainPID']) > 0,
                'Paired monitor is not running')
        return {'both_ranks_running': True, 'rank_identities_unchanged': True,
                'rank_restarts': 0, 'monitor_active': True,
                'available_gib': {host: pair.memory(host)['MemAvailable'] / 2**30
                                  for host in ('head', 'worker')}}

    record = dict(schema_version=1, status='running', started=now(),
                  runtime_source=revision, runtime_image=launch['image'],
                  model='DeepSeek-V4.1-Flash-Keys',
                  kit_sha256=sha(ROOT / 'tools/dsv41/kit_bench.py'),
                  runner_sha256=sha(Path(__file__)),
                  profile_sha256=sha(source / 'deployment/config/profile.json'),
                  protocol=dict(set='b', temperature=0, thinking=False,
                                input_padding=False, eos_allowed=True,
                                warmup_tokens=32, maximum_reply_tokens=384, repetitions=3,
                                decode_rate='(completion_tokens - 1) / first-to-last-content seconds',
                                cache_scope='Per-prompt warm-up; no cold-prefix claim'),
                  requests=[])

    def save():
        temp = out.with_name(out.name + '.tmp')
        temp.write_text(json.dumps(record, indent=2) + '\n')
        temp.replace(out)

    def counters(health):
        return dict(requests=health['completed']['requests'],
                    prompt_tokens=health['completed']['prompt_tokens'],
                    output_tokens=health['scheduler']['generation_tokens_total'])

    class CheckedClient(kit.Client):
        def health(self):
            health = self.get('/health', timeout=15)
            require(ready(health, profile()), 'Server is not ready or the profile differs')
            return health

        def idle(self, timeout=0):
            deadline = time.monotonic() + timeout
            while True:
                h = self.health()
                if h['scheduler']['running'] == h['scheduler']['waiting'] == 0:
                    return h
                require(time.monotonic() < deadline, 'Other requests are active; benchmark refused')
                time.sleep(.02)

        def stream(self, body, path):
            before = counters(self.idle())
            name = next(name for name, prompt in kit.PROMPT_SETS['b']
                        if prompt == body['messages'][0]['content'])
            result = super().stream(body, path)
            after = counters(self.idle(timeout=30))
            require(type(result['tokens']) is int and result['tokens'] > 1,
                    'Missing generated-token count')
            require(result['decode_s'] is not None and result['decode_s'] > 0,
                    'Missing content timing')
            require(after['requests'] - before['requests'] == 1, 'Request-counter contamination')
            require(after['output_tokens'] - before['output_tokens'] == result['tokens'],
                    'Output-token-counter contamination')
            require(after['prompt_tokens'] - before['prompt_tokens'] == result['prompt_tokens'],
                    'Input-token-counter contamination')
            phase = 'warmup' if body['max_tokens'] == 32 else 'scored'
            record['requests'].append(dict(prompt=name, phase=phase,
                repetition=sum(r['prompt'] == name and r['phase'] == phase for r in record['requests']),
                maximum_reply_tokens=body['max_tokens'], prompt_tokens=result['prompt_tokens'],
                generated_tokens=result['tokens'], ttft_s=result['ttft_s'],
                first_to_last_content_s=result['decode_s'], decode_output_tps=result['decode_tps'],
                wall_s=result['end'] - result['start'], chunks=result['chunks'],
                text_sha256=hashlib.sha256(result['text'].encode()).hexdigest(),
                counters_before=before, counters_after=after))
            save()
            return result

    client = CheckedClient(base, record['model'], None)
    # Reserve the path before any inference; never overwrite an earlier attempt.
    with out.open('x') as f:
        f.write(json.dumps(record, indent=2) + '\n')
    try:
        record['before'] = ranks()
        record['counters_before'] = counters(client.idle())
        save()
        results = kit.cmd_decode(client, SimpleNamespace(set='b', tokens=384, reps=3))
        record['decode'] = [{k: v for k, v in row.items() if k != 'sample'} for row in results]
        record['counters_after'] = counters(client.idle())
        record['after'] = ranks()
        require(git('rev-parse', 'HEAD') == revision and not git('status', '--porcelain'),
                'Serving source changed during benchmark')
        requests = record['requests']
        scored = [r for r in requests if r['phase'] == 'scored']
        require(len(requests) == 12 and len(scored) == 9, 'Incomplete kit run')
        require(record['counters_after']['requests'] - record['counters_before']['requests'] == 12,
                'Other requests contaminated the complete run')
        for row in record['decode']:
            runs = [r for r in scored if r['prompt'] == row['prompt']]
            require(len(runs) == 3 and statistics.median(r['decode_output_tps'] for r in runs)
                    == row['decode_tps_median'], 'Kit summary differs from recorded timings')
        record['all_scored_replies_reached_cap'] = all(r['generated_tokens'] == 384 for r in scored)
        record['checks'] = dict(owned_rank_identity=True, no_rank_restart=True,
                               exact_request_and_token_counters=True, unchanged_kit=True,
                               all_repetitions_retained=True, no_host_or_server_configuration_changes=True)
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
