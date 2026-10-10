"""Synthetic CPU-grammar pressure probe; never replay user requests.

Run only between acceptance jobs on the selected idle pair. --describe performs
no network/host access, and does not import the installed qualification binding.
"""
import argparse
import concurrent.futures
import hashlib
import json
import re
import threading
import time


def fixture(variant, tool_count, kind):
    """Short fixed answers, independently named schemas and strict tool sets."""
    answer = {'case': f'synthetic-{variant}', 'item': variant % 97,
              'options': {'mode': 'read', 'enabled': True}}
    schema = {'type': 'object', 'properties': {
        'case': {'type': 'string', 'enum': [answer['case']]},
        'item': {'type': 'integer', 'enum': [answer['item']]},
        'options': {'type': 'object', 'properties': {
            'mode': {'type': 'string', 'enum': ['read']},
            'enabled': {'type': 'boolean', 'enum': [True]}},
            'required': ['mode', 'enabled'], 'additionalProperties': False}},
        'required': ['case', 'item', 'options'], 'additionalProperties': False}
    body = dict(max_tokens=384, temperature=0,
                chat_template_kwargs={'enable_thinking': False})
    expected = dict(answer=answer, kind=kind, names=[])
    if kind == 'tools':
        names = [f'inspect_case_{variant}_{i}' for i in range(tool_count)]
        expected['names'] = names
        body.update(tools=[{'type': 'function', 'function': {
            'name': name, 'description': 'Inspect a synthetic record without modifying it.',
            'strict': True, 'parameters': schema}} for name in names],
            tool_choice='required', parallel_tool_calls=False,
            messages=[{'role': 'user', 'content':
                'Call '+names[0]+' exactly once, using these arguments: '+json.dumps(answer)}])
    else:
        body.update(response_format={'type': 'json_schema', 'json_schema': {
            'name': f'synthetic_answer_{variant}', 'strict': True, 'schema': schema}},
            messages=[{'role': 'user', 'content': 'Return exactly this JSON object: '+json.dumps(answer)}])
    return body, expected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--record')
    parser.add_argument('--streams', type=int, default=4)
    parser.add_argument('--tools', type=int, default=8)
    parser.add_argument('--rounds', type=int, default=4)
    parser.add_argument('--variant-base', type=int, default=0,
                        help='Offset fixture names and constants for fresh schemas in repeated cycles')
    parser.add_argument('--mode', choices=('tools', 'json', 'mixed'), default='mixed')
    parser.add_argument('--describe', action='store_true')
    args = parser.parse_args()
    assert 1 <= args.streams <= 32 and 1 <= args.tools <= 64 and 1 <= args.rounds <= 64
    assert 0 <= args.variant_base <= 10**9

    def cases(round_index):
        return [fixture(args.variant_base+round_index*args.streams+i, args.tools,
                        ('tools' if i % 2 == 0 else 'json') if args.mode == 'mixed' else args.mode)
                for i in range(args.streams)]

    if args.describe:
        example, _ = fixture(args.variant_base, args.tools, 'tools')
        print(json.dumps(dict(streams=args.streams, rounds=args.rounds,
            distinct_schemas=args.streams*args.rounds, tools_per_tool_request=args.tools,
            final_replay_requests=args.streams, example_tool_request_bytes=len(json.dumps(example).encode()),
            mode=args.mode, variant_base=args.variant_base, inference_sent=False), indent=2))
        return
    assert args.record and re.fullmatch('[a-z0-9-]+', args.record)
    from common import PAIR, ROOT, atomic, now
    path = ROOT/('records/validation-'+args.record+'-schema-churn.json')
    assert not path.exists(), 'Preserve previous attempts; choose a fresh record prefix'
    from cluster import get
    from qualify import post
    from memory_watch import health_sample

    before = get('/health')
    assert before['ok'] and not before['requests_running'] and not before.get('busy')
    launch = json.loads((PAIR.state/'launch.json').read_text())
    record = dict(started=now(), status='running', parameters=vars(args), image=launch['image'],
                  containers=launch['containers'], health_before=health_sample(before), waves=[], samples=[],
                  total_samples=0, retained_sample_limit=4096,
                  fixtures='New generated constant JSON objects and named strict tool sets; no user inputs')
    finished = threading.Event()
    lock = threading.Lock()

    def save():
        with lock:
            atomic(path, record)

    def observe():
        while not finished.is_set():
            sample = {'time': now()}
            try:
                sample['health'] = health_sample(get('/health', timeout=5))
                f = PAIR.state/'memory/samples.jsonl'
                with f.open('rb') as stream:
                    stream.seek(max(0, f.stat().st_size-128*1024))
                    memory = json.loads(stream.read().splitlines()[-1])
                sample['memory_time'] = memory['time']
                sample['hosts'] = {host:dict(
                    meminfo={key:row['meminfo'][key] for key in ('MemAvailable','AnonPages','SwapFree','Slab')},
                    rank_rss_sum_bytes=row['rank_rss_sum_bytes'],
                    rank_anon_plus_swap_bytes=sum(proc.get('RssAnon',0)+proc.get('VmSwap',0)
                                                 for proc in row.get('rank_processes',[])))
                    for host,row in memory['hosts'].items()}
            except Exception as exc:
                sample['error'] = type(exc).__name__
            with lock:
                record['samples'].append(sample)
                del record['samples'][:-record['retained_sample_limit']]
                record['total_samples'] += 1
            finished.wait(5)

    def check():
        h = get('/health')
        assert h['ok'] and not h['requests_running'] and not h.get('fatal')
        assert h['memory']['round_graphs_sealed']
        for field in ('allocation_ooms', 'allocation_retries', 'round_graph_captures'):
            assert h['memory'][field] == before['memory'][field], field+' changed'
        for host in ('head', 'worker'):
            rows = PAIR.containers(host)
            assert len(rows) == 1 and rows[0]['State']['Running']
            assert rows[0]['Id'] == launch['containers'][host] and rows[0]['Image'] == launch['image']
        return health_sample(h)

    def wave(label, probes):
        gate = threading.Barrier(len(probes))
        def send(probe):
            body, expected = probe
            gate.wait(timeout=30)
            output = post(body, timeout=900)
            result = output['response']
            choice = result['choices'][0]
            assert choice['finish_reason'] != 'length', 'incomplete structured reply'
            if expected['kind'] == 'tools':
                calls = choice['message'].get('tool_calls', [])
                assert len(calls) == 1 and calls[0]['function']['name'] in expected['names']
                actual = json.loads(calls[0]['function']['arguments'])
            else:
                actual = json.loads(choice['message']['content'])
            assert actual == expected['answer'], 'synthetic strict-schema answer did not match'
            assert result.get('tensorfold', {}).get('drafts') is False
            encoded = json.dumps(body, sort_keys=True).encode()
            return dict(kind=expected['kind'], request_sha256=hashlib.sha256(encoded).hexdigest(),
                        request_bytes=len(encoded), seconds=output['seconds'], usage=result['usage'])
        item = dict(name=label, started=now(), results=[], errors=[])
        with lock:
            record['waves'].append(item)
        save()
        print(now(), label, 'starting', len(probes), 'requests', flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(probes)) as pool:
            futures = [pool.submit(send, case) for case in probes]
            for future in futures:
                try:
                    result = future.result()
                    with lock:
                        item['results'].append(result)
                except Exception as exc:
                    with lock:
                        item['errors'].append(type(exc).__name__+': '+str(exc))
        with lock:
            item['finished'] = now()
        save()
        assert not item['errors'], label+' request failure; preserve receipt'
        health = check()
        with lock:
            item['health_after'] = health
        save()
        print(now(), label, 'passed', flush=True)

    watcher = threading.Thread(target=observe, daemon=True)
    watcher.start()
    save()
    try:
        for round_index in range(args.rounds):
            wave(f'cold-{round_index:02d}', cases(round_index))
        wave('first-wave-replay', cases(0))
        final = check()
        with lock:
            record.update(status='passed', health_after=final)
    except (KeyboardInterrupt, SystemExit) as exc:
        with lock:
            record.update(status='interrupted', error=type(exc).__name__+': '+str(exc))
        raise
    except BaseException as exc:
        with lock:
            record.update(status='failed', error=type(exc).__name__+': '+str(exc))
        raise
    finally:
        finished.set(); watcher.join(timeout=10)
        with lock:
            record['finished'] = now()
        save()


if __name__ == '__main__':
    main()
