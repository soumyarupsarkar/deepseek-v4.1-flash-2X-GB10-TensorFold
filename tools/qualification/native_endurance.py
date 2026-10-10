"""New, bounded synthetic native qualification. Never resumes an earlier run."""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import signal
import subprocess
import sys
import time

SOURCE = Path(__file__).resolve().parents[2]
MAX_EVIDENCE_BYTES = 64 * 2**20
GATES = {'features', 'parity', 'retention', 'compaction', 'capacity', 'million', 'recovery', 'matched-benefit'}


def compact_result(result):
    response = result['response']
    tf = response.get('tensorfold', {})
    usage = response.get('usage', {})
    return dict(seconds=result['seconds'],
                usage={k: usage[k] for k in ('prompt_tokens', 'completion_tokens', 'total_tokens') if k in usage},
                token_sha=tf.get('token_sha'),
                sampling_seed=tf.get('sampling_seed'),
                cached=tf.get('cached'), drafts=tf.get('drafts'))


def append(path, value):
    line = (json.dumps(value, separators=(',', ':'), allow_nan=False) + '\n').encode()
    if len(line) > 2**20 or path.stat().st_size + len(line) > MAX_EVIDENCE_BYTES:
        raise RuntimeError('Bounded endurance evidence limit reached; preserving all earlier records')
    with path.open('ab') as stream:
        stream.write(line)


def validate_gates(gates, launch, source):
    if (gates.get('status') != 'passed' or set(gates.get('passed', [])) != GATES
            or gates.get('image') != launch['image'] or gates.get('source') != source):
        raise RuntimeError('Feature/capacity/performance gates must pass for this exact source and image')
    if not gates.get('receipts'):
        raise RuntimeError('Require preserved prerequisite receipts')
    for receipt in gates['receipts']:
        if hashlib.sha256(Path(receipt['path']).read_bytes()).hexdigest() != receipt['sha256']:
            raise RuntimeError('A prerequisite receipt changed')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--record', required=True)
    p.add_argument('--gates', type=Path, required=True)
    p.add_argument('--hours', type=float, default=24)
    a = p.parse_args()
    if not a.record.replace('-', '').isalnum() or not 0 < a.hours <= 24:
        raise ValueError('Invalid record name or duration')
    sys.path.insert(0, str(SOURCE / 'tools/qualification'))
    import common
    from cluster import get, memory
    from configuration import profile, read, STATE
    from engine_health import ready
    from memory_watch import health_sample
    from benchmark import wave
    from qualify import post, text, vision

    gates = json.loads(a.gates.read_text())
    launch = read(STATE / 'launch.json')
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=SOURCE, text=True).strip()
    validate_gates(gates, launch, source)
    if common.PAIR.config['api']['bind'] != '127.0.0.1':
        raise RuntimeError('Require an isolated loopback candidate')
    directory = common.ROOT / 'endurance' / a.record
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    evidence = directory / 'cycles.jsonl'
    evidence.touch(mode=0o600, exist_ok=False)
    record_path = directory / 'status.json'
    started = time.monotonic()
    deadline, next_quiet = started + a.hours * 3600, started + 3600
    record = dict(started=common.now(), status='running', hours=a.hours, source=source,
                  image=launch['image'], launch=launch, gates_sha256=hashlib.sha256(a.gates.read_bytes()).hexdigest(),
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  completed_cycles=0, deep_waves=0, quiet_windows=0, cycle_requests=0,
                  evidence_limit_bytes=MAX_EVIDENCE_BYTES, previous_run_resumed=False)
    interrupted = False

    def save():
        record['updated'] = common.now()
        record['elapsed_s'] = time.monotonic() - started
        common.atomic(record_path, record)

    def stop_signal(signum, _frame):
        nonlocal interrupted
        interrupted = True
        record.update(status='interrupted', signal=signum)
        save()
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)

    def sample():
        health = get('/health')
        if not ready(health, profile()) or health['scheduler']['running'] or health['scheduler']['waiting']:
            raise RuntimeError('Endurance pair is unhealthy or did not become idle')
        rss = next(int(line.split()[1]) * 1024 for line in Path('/proc/self/status').read_text().splitlines()
                   if line.startswith('VmRSS:'))
        return dict(time=common.now(), health=health_sample(health), client_rss_bytes=rss,
                    available_bytes={host: memory(host)['MemAvailable'] for host in ('head', 'worker')})

    def canary():
        body = dict(messages=[{'role': 'user', 'content':
            'Give three concise improvements for a Python function that appends an item to a mutable default list.'}],
            max_tokens=128, temperature=1, seed=73, chat_template_kwargs={'enable_thinking': False})
        reply = post(body)
        if not text(reply).strip():
            raise AssertionError('Empty synthetic replay canary')
        digest = reply['response']['tensorfold']['token_sha']
        if not digest or ('canary_sha' in record and digest != record['canary_sha']):
            raise AssertionError('Fixed-seed solo canary changed')
        record['canary_sha'] = digest
        return compact_result(reply)

    def ordinary(cycle, slot):
        lines = ''.join(f'Record {i}: copper value {(i * 7919 + slot * 313) % 100003}, item-{slot}-{i}.\n'
                        for i in range(40 + (slot % 4) * 65))
        return post(dict(messages=[{'role': 'user', 'content': lines +
            f'\nSummarize this synthetic table in five concise observations. Cycle {cycle}.'}],
            max_tokens=96, temperature=0, chat_template_kwargs={'enable_thinking': False}))

    def schema(cycle):
        expected = {'status': 'ok', 'value': cycle % 128}
        spec = dict(type='object', properties={k: {'const': v} for k, v in expected.items()},
                    required=list(expected), additionalProperties=False)
        result = post(dict(messages=[{'role': 'user', 'content': 'Return the required JSON object.'}],
            max_tokens=128, temperature=0, chat_template_kwargs={'enable_thinking': False},
            response_format={'type': 'json_schema', 'json_schema': {'name': 'endurance', 'strict': True, 'schema': spec}}))
        if json.loads(text(result)) != expected:
            raise AssertionError('Schema result differs')
        return result

    def tool():
        result = post(dict(messages=[{'role': 'user', 'content': 'Use the status tool to report ok.'}],
            tools=[{'type': 'function', 'function': {'name': 'status', 'strict': True,
                'parameters': {'type': 'object', 'properties': {'value': {'const': 'ok'}},
                               'required': ['value'], 'additionalProperties': False}}}],
            tool_choice='required', parallel_tool_calls=False, max_tokens=128, temperature=0,
            chat_template_kwargs={'enable_thinking': False}))
        calls = result['response']['choices'][0]['message'].get('tool_calls', [])
        if len(calls) != 1 or calls[0]['function']['name'] != 'status' or json.loads(calls[0]['function']['arguments']) != {'value': 'ok'}:
            raise AssertionError('Required tool result differs')
        return result

    save()
    try:
        append(evidence, dict(kind='initial', sample=sample(), canary=canary()))
        while time.monotonic() < deadline:
            cycle = record['completed_cycles']
            with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
                jobs = [pool.submit(ordinary, cycle, slot) for slot in range(29)]
                jobs += [pool.submit(schema, cycle), pool.submit(tool),
                         pool.submit(vision, (240, 20, 20) if cycle % 2 == 0 else (20, 20, 240))]
                results = [job.result() for job in jobs]
            if ('red' if cycle % 2 == 0 else 'blue') not in text(results[-1]).lower():
                raise AssertionError('Synthetic image color differs')
            if any(not text(result).strip() for result in results[:29]):
                raise AssertionError('Empty table response')
            append(evidence, dict(kind='cycle', cycle=cycle, time=common.now(),
                requests=[compact_result(result) for result in results], canary=canary(), sample=sample()))
            record['completed_cycles'] += 1
            record['cycle_requests'] += 33
            if cycle % 4 == 0 and deadline - time.monotonic() > 900:
                size = (32768, 131072, 262144, 614400, 1048320)[(cycle // 4) % 5]
                case = dict(streams=1, prompt_tokens=size, reply_tokens=256, prompt_class='code',
                            cache='cold', mode='default', temperature=0, seed=520000 + cycle)
                row = wave(common.API_BASE, case, 600000 + cycle)
                append(evidence, dict(kind='deep', cycle=cycle, case=case, summary=row['summary'],
                                     native_graph_captures_during_wave=row.get('native_graph_captures_during_wave'),
                                     sample=sample()))
                record['deep_waves'] += 1
            if time.monotonic() >= next_quiet:
                before = sample()
                time.sleep(min(120, max(0, deadline - time.monotonic())))
                append(evidence, dict(kind='quiet', before=before, after=sample()))
                record['quiet_windows'] += 1
                next_quiet = time.monotonic() + 3600
            save()
            print('cycle', cycle, 'passed; elapsed', round(record['elapsed_s']), 'seconds', flush=True)
            time.sleep(min(5, max(0, deadline - time.monotonic())))
        append(evidence, dict(kind='final', sample=sample(), canary=canary()))
        record['status'] = 'passed'
    except BaseException as exc:
        if not interrupted:
            record.update(status='failed', error=type(exc).__name__ + ': ' + str(exc))
            save()
            # The controller checks exact ownership. Also refuse to touch a
            # replacement installation if its launch identity changed mid-run.
            try:
                if read(STATE / 'launch.json')['containers'] == launch['containers']:
                    with (directory / 'fault-stop.log').open('x') as output:
                        result = subprocess.run(['python3', '-B', 'cluster', 'stop'], cwd=SOURCE,
                                                stdout=output, stderr=subprocess.STDOUT, timeout=180)
                    record['fault_stop_exit'] = result.returncode
                else:
                    record['fault_stop_skipped'] = 'launch identity changed'
            except Exception as cleanup:
                record['fault_stop_error'] = type(cleanup).__name__ + ': ' + str(cleanup)
        raise
    finally:
        record['finished'] = common.now()
        save()


if __name__ == '__main__':
    main()
