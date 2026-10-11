"""New, bounded synthetic native qualification. Never resumes an earlier run."""
import argparse
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

SOURCE = Path(__file__).resolve().parents[2]
MAX_EVIDENCE_BYTES = 64 * 2**20
GATES = {'features', 'parity', 'retention', 'compaction', 'capacity', 'million', 'prefill-responsiveness',
         'recovery', 'matched-benefit'}
DIAGNOSTIC_FEATURES = {'baseline', 'structured', 'sampling', 'aliases', 'protocols',
                       'constraints-greedy', 'constraints-sampled', 'retention', 'pool',
                       'c32-full', 'million'}


class TrafficInterference(RuntimeError):
    """Invalidate an isolated observation without shutting down a healthy server."""


def validate_diagnostic(receipt, launch, source):
    """Finite serving/capacity evidence permits observation, not release qualification."""
    p = launch['profile']
    required_capacity = dict(pool_tokens=p['pool_tokens'], max_request_tokens=p['context'],
                             streams=p['parallel'], round_rows=int(p['environment']['TF_DS_ROUND_ROWS']))
    features = {r['name'] for r in receipt.get('feature_checks', []) if r.get('status') == 'passed'}
    full = receipt.get('full_capacity', {})
    if (receipt.get('status') != 'finite-validation-passed; endurance and production cutover held'
            or receipt.get('runtime_source') != source or receipt.get('runtime_image') != launch['image']
            or receipt.get('capacity') != required_capacity or not DIAGNOSTIC_FEATURES <= features
            or not full.get('cycles') or not full.get('independent_active_extents')
            or full.get('replay_parity_passed') is not True
            or any(c.get('peak_decoding') != p['parallel'] for c in full['cycles'])
            or receipt.get('million', {}).get('usage', {}).get('total_tokens') != p['context']
            or receipt.get('million', {}).get('retrieval_passphrases_correct') != 3):
        raise RuntimeError('Diagnostic requires matching finite feature, C32 and million-token evidence')


def check_request_delta(before, after, expected):
    if after - before != expected:
        raise TrafficInterference(f'Unexpected request-counter delta: {after - before}, expected {expected}')


def latest_monitor_sample(path, image, max_age=45):
    """Read one bounded, complete record, including while the monitor appends."""
    with path.open('rb') as stream:
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(max(0, size - 262144))
        raw = stream.read()
    lines = raw.split(b'\n')
    for line in reversed(lines[:-1]):
        try:
            row = json.loads(line)
            break
        except (ValueError, UnicodeError):
            continue
    else:
        raise RuntimeError('No complete bounded memory-monitor record')
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(row['time'])).total_seconds()
    if row.get('image') != image or not 0 <= age <= max_age:
        raise RuntimeError('Memory-monitor record is stale or belongs to another image')
    return row


def memory_summary(path):
    """Keep swap, file cache and RSS visible; a falling MemAvailable alone is not a leak."""
    hosts = {name: dict(samples=0) for name in ('head', 'worker')}
    errors = 0
    with path.open() as stream:
        for line in stream:
            row = json.loads(line)
            if 'observer_error' in row:
                errors += 1
                continue
            for host, result in hosts.items():
                sample = row.get('hosts', {}).get(host, {})
                mem = sample.get('meminfo', {})
                if 'MemAvailable' not in mem:
                    continue
                values = dict(available_bytes=mem['MemAvailable'],
                    swap_used_bytes=mem['SwapTotal'] - mem['SwapFree'],
                    rank_rss_bytes=sample.get('rank_rss_sum_bytes'),
                    cgroup_anon_bytes=sample.get('cgroup', {}).get('memory.stat', {}).get('anon'),
                    cgroup_file_bytes=sample.get('cgroup', {}).get('memory.stat', {}).get('file'))
                if not result['samples']:
                    result.update(first=values, first_time=row['time'], minimum_available_bytes=mem['MemAvailable'])
                result.update(last=values, last_time=row['time'], samples=result['samples'] + 1,
                              minimum_available_bytes=min(result['minimum_available_bytes'], mem['MemAvailable']))
                result['delta_bytes'] = {k: values[k] - result['first'][k] for k in values
                    if values[k] is not None and result['first'][k] is not None}
    return dict(hosts=hosts, observer_errors=errors, interpretation='Review matched quiet windows before attributing growth')


def compact_result(result):
    response = result['response']
    tf = response.get('tensorfold', {})
    usage = response.get('usage', {})
    return dict(seconds=result['seconds'],
                usage={k: usage[k] for k in ('prompt_tokens', 'completion_tokens', 'total_tokens') if k in usage},
                token_sha=tf.get('token_sha'),
                sampling_seed=tf.get('sampling_seed'),
                cached=usage.get('prompt_tokens_details', {}).get('cached_tokens', tf.get('cached')),
                drafts=tf.get('drafts'))


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


def rank_epochs(pair, launch):
    """Bind endurance to running processes, including same-container restarts."""
    pair.ownership()
    epochs = {}
    for host in ('head', 'worker'):
        rows = pair.containers(host)
        if len(rows) != 1:
            raise RuntimeError(host + ': require one owned endurance rank')
        row = rows[0]
        state = row.get('State', {})
        started = state.get('StartedAt')
        restarts = row.get('RestartCount')
        if (row.get('Id') != launch['containers'][host] or row.get('Image') != launch['image']
                or state.get('Running') is not True or state.get('Paused') or state.get('Restarting')
                or not isinstance(started, str) or not started or started.startswith('0001-')
                or type(restarts) is not int or restarts < 0):
            raise RuntimeError(host + ': endurance rank identity or running state differs')
        epochs[host] = dict(container=row['Id'], image=row['Image'], started=started, restarts=restarts)
    return epochs


def validate_continuity(pair, expected_launch, expected_epochs, current_launch, active):
    if (current_launch != expected_launch or active.get('running') is not True
            or active.get('image') != expected_launch['image']
            or active.get('containers') != expected_launch['containers']):
        raise RuntimeError('Endurance launch changed or stopped; do not combine separate runs')
    if rank_epochs(pair, expected_launch) != expected_epochs:
        raise RuntimeError('An endurance rank restarted; do not combine separate runs')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--record', required=True)
    p.add_argument('--gates', type=Path)
    p.add_argument('--hours', type=float, default=24)
    p.add_argument('--source', type=Path, default=SOURCE, help='Clean checkout owning the running deployment')
    p.add_argument('--diagnostic-prerequisites', type=Path,
                   help='Finite throughput/feature/capacity receipt; selects a diagnostic of at most four hours')
    a = p.parse_args()
    diagnostic = a.diagnostic_prerequisites is not None
    if (not a.record.replace('-', '').isalnum() or not math.isfinite(a.hours)
            or not 0 < a.hours <= (4 if diagnostic else 24)
            or (diagnostic and a.gates) or (not diagnostic and not a.gates)):
        raise ValueError('Invalid record name or duration')
    deployment_source = a.source.resolve()
    sys.path.insert(0, str(deployment_source / 'tools/qualification'))
    import common
    from cluster import memory
    from configuration import profile, read, STATE
    from engine_health import ready
    from memory_watch import health_sample, host_sample
    from benchmark import wave, wait_idle, evict
    from qualify import post, text, vision

    prerequisite_path = a.diagnostic_prerequisites if diagnostic else a.gates
    gates = json.loads(prerequisite_path.read_text())
    launch = read(STATE / 'launch.json')
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=deployment_source, text=True).strip()
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=deployment_source, text=True).strip():
        raise RuntimeError('Serving checkout must be clean')
    build = read(STATE / 'build.json')
    if build['revision'] != source or build['id'] != launch['image'] or profile() != launch['profile']:
        raise RuntimeError('Serving source, image or profile differs from the launch')
    if diagnostic:
        validate_diagnostic(gates, launch, source)
    else:
        validate_gates(gates, launch, source)
    if not diagnostic and common.PAIR.config['api']['bind'] != '127.0.0.1':
        raise RuntimeError('Require an isolated loopback candidate')
    epochs = rank_epochs(common.PAIR, launch)
    validate_continuity(common.PAIR, launch, epochs, read(STATE / 'launch.json'), read(STATE / 'active.json'))
    directory = common.ROOT / 'endurance' / a.record
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    evidence = directory / 'cycles.jsonl'
    evidence.touch(mode=0o600, exist_ok=False)
    memory_evidence = directory / 'memory.jsonl'
    memory_evidence.touch(mode=0o600, exist_ok=False)
    record_path = directory / 'status.json'
    started = time.monotonic()
    deadline, next_quiet = started + a.hours * 3600, started + 3600
    record = dict(started=common.now(), status='running', hours=a.hours, source=source,
                  image=launch['image'], launch=launch, gates_sha256=hashlib.sha256(prerequisite_path.read_bytes()).hexdigest(),
                  mode='serving-diagnostic' if diagnostic else 'release-qualification',
                  full_release_qualification=False, memory_review='pending', phase='initializing',
                  target_finish=datetime.fromtimestamp(time.time() + a.hours * 3600, timezone.utc).isoformat(),
                  rank_epochs=epochs,
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  completed_cycles=0, deep_waves=0, quiet_windows=0, cycle_requests=0,
                  evidence_limit_bytes=MAX_EVIDENCE_BYTES, previous_run_resumed=False)
    interrupted = False
    stop_observer = threading.Event()
    observer_errors = []
    last_requests = None
    frozen_files = [Path(__file__), prerequisite_path,
        *(deployment_source / name for name in ('tools/qualification/common.py', 'tools/qualification/qualify.py',
          'deployment/scripts/benchmark.py', 'deployment/scripts/runtime.py', 'deployment/scripts/configuration.py',
          'deployment/scripts/engine_health.py', 'deployment/scripts/memory_watch.py',
          'deployment/scripts/memory_probe.py', 'deployment/config/profile.json'))]
    record['client_inputs'] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in frozen_files}

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

    def sample(expected=0, detail=False):
        nonlocal last_requests
        if observer_errors:
            raise RuntimeError('Memory observer failed: ' + observer_errors[-1])
        if any(hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest
               for path, digest in record['client_inputs'].items()):
            raise RuntimeError('A frozen client or prerequisite file changed')
        validate_continuity(common.PAIR, launch, epochs, read(STATE / 'launch.json'), read(STATE / 'active.json'))
        subprocess.run(['systemctl', 'is-active', '--quiet', common.PAIR.unit()], check=True, timeout=10)
        health, drain = wait_idle(common.API_BASE)
        if not ready(health, profile()) or health['scheduler']['running'] or health['scheduler']['waiting']:
            raise RuntimeError('Endurance pair is unhealthy or did not become idle')
        if last_requests is not None:
            check_request_delta(last_requests, health['completed']['requests'], expected)
        last_requests = health['completed']['requests']
        latest_monitor_sample(STATE / 'memory/samples.jsonl', launch['image'])
        rss = next(int(line.split()[1]) * 1024 for line in Path('/proc/self/status').read_text().splitlines()
                   if line.startswith('VmRSS:'))
        result = dict(time=common.now(), health=health_sample(health), client_rss_bytes=rss,
                    post_response_drain_seconds=drain['seconds'],
                    available_bytes={host: memory(host)['MemAvailable'] for host in ('head', 'worker')})
        if detail:
            result['hosts'] = {host: host_sample(common.PAIR, host, common.PAIR.containers(host)[0]['State']['Pid'],
                floor_bytes=int(profile()['minimum_available_gib'] * 2**30), detail=True) for host in ('head', 'worker')}
        return result

    def observe_memory():
        previous = None
        failures = 0
        while not stop_observer.is_set():
            try:
                row = latest_monitor_sample(STATE / 'memory/samples.jsonl', launch['image'])
                if row['time'] != previous:
                    append(memory_evidence, row)
                    previous = row['time']
                failures = 0
            except Exception as exc:
                failures += 1
                message = type(exc).__name__ + ': ' + str(exc)
                try:
                    append(memory_evidence, dict(time=common.now(), observer_error=message))
                except Exception:
                    failures = 3
                if failures >= 3:
                    observer_errors.append(message)
                    return
                # File rotation or an incomplete append must not stop a healthy pair.
                stop_observer.wait(1)
                continue
            stop_observer.wait(10)

    def quiet(label):
        record['phase'] = 'normalizing-' + label
        save()
        normalization = evict(common.API_BASE, 810000 + record['quiet_windows'])
        before = sample(expected=64, detail=True)
        record['phase'] = 'quiet-' + label
        save()
        time.sleep(120)
        after = sample(detail=True)
        append(evidence, dict(kind='quiet', label=label, normalization=normalization, before=before, after=after))
        record.setdefault('quiet_memory', []).append(dict(label=label, time=after['time'],
            available_bytes=after['available_bytes'],
            retained_states=after['health']['native']['retained_states'],
            snapshot_bytes=after['health']['native']['snapshot_bytes'],
            graphs=after['health']['native']['round_graphs']))
        record['quiet_windows'] += 1
        save()

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
    observer = threading.Thread(target=observe_memory, daemon=True)
    observer.start()
    try:
        initial = sample(detail=True)
        initial_canary = canary()
        append(evidence, dict(kind='initial', sample=initial, canary=initial_canary, after=sample(expected=1)))
        quiet('baseline')
        while time.monotonic() < deadline:
            cycle = record['completed_cycles']
            record['phase'] = 'mixed-cycle-' + str(cycle)
            save()
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
                requests=[compact_result(result) for result in results], canary=canary(), sample=sample(expected=33)))
            record['completed_cycles'] += 1
            record['cycle_requests'] += 33
            if cycle % 4 == 0 and deadline - time.monotonic() > 900:
                size = (32768, 131072, 262144, 614400, 1048320)[(cycle // 4) % 5]
                case = dict(streams=1, prompt_tokens=size, reply_tokens=256, prompt_class='code',
                            cache='cold', mode='default', temperature=0, seed=520000 + cycle)
                record['phase'] = 'deep-' + str(size)
                save()
                row = wave(common.API_BASE, case, 600000 + cycle)
                append(evidence, dict(kind='deep', cycle=cycle, case=case, summary=row['summary'],
                                     native_graph_captures_during_wave=row.get('native_graph_captures_during_wave'),
                                     sample=sample(expected=65)))
                record['deep_waves'] += 1
                del row
            if next_quiet <= time.monotonic() < deadline - 300:
                quiet('hourly')
                next_quiet = time.monotonic() + 3600
            save()
            print('cycle', cycle, 'passed; elapsed', round(record['elapsed_s']), 'seconds', flush=True)
            time.sleep(min(5, max(0, deadline - time.monotonic())))
        append(evidence, dict(kind='final-canary', canary=canary(), sample=sample(expected=1)))
        quiet('final')
        record.update(status='diagnostic-workload-passed' if diagnostic else 'passed', phase='finished')
    except BaseException as exc:
        if not interrupted:
            record.update(status='failed', error=type(exc).__name__ + ': ' + str(exc))
            save()
            # The controller checks exact ownership. Also refuse to touch a
            # replacement installation if its launch identity changed mid-run.
            try:
                if isinstance(exc, TrafficInterference):
                    record['fault_stop_skipped'] = 'Other traffic invalidated the observation; healthy serving left to watchdog'
                elif read(STATE / 'launch.json')['containers'] == launch['containers']:
                    with (directory / 'fault-stop.log').open('x') as output:
                        result = subprocess.run(['python3', '-B', 'cluster', 'stop'], cwd=deployment_source,
                                                stdout=output, stderr=subprocess.STDOUT, timeout=180)
                    record['fault_stop_exit'] = result.returncode
                else:
                    record['fault_stop_skipped'] = 'launch identity changed'
            except Exception as cleanup:
                record['fault_stop_error'] = type(cleanup).__name__ + ': ' + str(cleanup)
        raise
    finally:
        stop_observer.set()
        observer.join(timeout=15)
        record['memory_summary'] = memory_summary(memory_evidence)
        record['finished'] = common.now()
        save()


if __name__ == '__main__':
    main()
