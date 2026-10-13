"""CPU-only native HTTP memory reproduction with synthetic code prompts.

Requires the scripted fake_serve binary and a local tokenizer/template directory.
Starts only that child on an ephemeral loopback port, never the GPU deployment.
All requests are generated here; no inference-server logs or prompts are read.
"""
import argparse
import concurrent.futures
import hashlib
import http.client
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--tokenizer', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New evidence directory')
    parser.add_argument('--fixtures', type=Path, default=Path(__file__).resolve().parents[2]/'zig/tests/server/fixtures')
    parser.add_argument('--parallel', type=int, default=32)
    parser.add_argument('--repeat', type=int, default=800)
    parser.add_argument('--chunks', type=int, default=4)
    parser.add_argument('--delay-ms', type=int, default=6000)
    parser.add_argument('--stream', action='store_true')
    parser.add_argument('--close', action='store_true', help='Close nonstreaming connections immediately')
    parser.add_argument('--max-rss-mib', type=float, help='Optional peak-RSS regression ceiling')
    args = parser.parse_args()
    if not (1 <= args.parallel <= 32 and 1 <= args.repeat <= 45000
            and 1 <= args.chunks <= 16384 and 0 <= args.delay_ms <= 10000
            and args.chunks * args.delay_ms <= 120000):
        parser.error('Require C1–32, 1–45000 repeats, 1–16384 chunks, and at most 120 seconds of scripted delay')
    args.binary, args.tokenizer = args.binary.resolve(), args.tokenizer.resolve()
    args.fixtures, args.output = args.fixtures.resolve(), args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    scripts = args.output/'scripts.json'
    scripts.write_text(json.dumps({'default': {'chunks': [[42]] * args.chunks, 'delay_ms': args.delay_ms}}))
    env = dict(os.environ, TF_FAKE_TOKENIZER=str(args.tokenizer), TF_FAKE_CONTEXT='1048576', TF_FAKE_SCRIPTS=str(scripts))
    connections, samples, results = [], [], []
    stop = threading.Event()
    sample_errors = []
    log_path = args.output/'server.log'
    record = dict(status='running', parameters={k: str(v) if isinstance(v, Path) else v for k,v in vars(args).items()},
                  binary_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                  tokenizer_sha256=hashlib.sha256((args.tokenizer/'tokenizer.json').read_bytes()).hexdigest(),
                  client_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    thread = None
    start = time.monotonic()
    with log_path.open('w') as log:
        proc = subprocess.Popen([str(args.binary), 'serve', str(args.fixtures), '--host', '127.0.0.1', '--port', '0',
            '--name', 'memory-test', '--parallel', str(args.parallel), '--no-thinking', '--keep-warm', '0'],
            env=env, stdout=log, stderr=log)

        def memory():
            values = {}
            for line in Path(f'/proc/{proc.pid}/status').read_text().splitlines():
                key, _, rest = line.partition(':')
                if key in ('RssAnon', 'VmRSS', 'VmSwap', 'VmHWM', 'Threads'):
                    values[key] = int(rest.split()[0]) * (1 if key == 'Threads' else 1024)
            values['anonymous_plus_swap'] = values['RssAnon'] + values['VmSwap']
            return values

        def sampler():
            try:
                while not stop.wait(.05):
                    samples.append(dict(t=round(time.monotonic()-start, 3), **memory()))
            except Exception as exc:
                sample_errors.append(type(exc).__name__ + ': ' + str(exc))

        def request(index):
            line = 'def synthetic_function(value):\n    return {"result": value * 7, "status": "synthetic"}\n'
            body = json.dumps(dict(model='memory-test', messages=[
                dict(role='system', content='Synthetic memory regression fixture.'),
                dict(role='user', content=str(index)+'\n'+line*args.repeat)],
                max_tokens=args.chunks+10, stream=args.stream, temperature=0))
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=240)
            connections.append(conn)
            conn.request('POST', '/v1/chat/completions', body=body, headers={
                'Content-Type': 'application/json', 'Connection': 'close' if args.close else 'keep-alive'})
            response = conn.getresponse()
            raw = response.read()
            if response.status != 200:
                raise RuntimeError(f'HTTP {response.status}: {raw[:300]!r}')
            if args.stream:
                frames = [json.loads(line[6:]) for line in raw.decode().splitlines() if line.startswith('data: {')]
                if not raw.endswith(b'data: [DONE]\n\n'):
                    raise RuntimeError('Stream missing DONE')
                if any('error' in f for f in frames):
                    raise RuntimeError('Stream returned an error')
                last = next(f for f in reversed(frames) if 'usage' in f)
                content = ''.join(c.get('delta', {}).get('content', '') or '' for f in frames for c in f.get('choices', []))
            else:
                last = json.loads(raw)
                content = last['choices'][0]['message'].get('content') or ''
            if last['usage']['completion_tokens'] != args.chunks:
                raise RuntimeError('Scripted generation did not complete')
            return dict(status=response.status, input_bytes=len(body), usage=last['usage'],
                        token_sha=last['tensorfold']['token_sha'], content_sha256=hashlib.sha256(content.encode()).hexdigest())

        try:
            for _ in range(600):
                if proc.poll() is not None:
                    raise RuntimeError(f'Child exited: {proc.returncode}')
                ports = [line for line in log_path.read_text().splitlines() if line.startswith('PORT ')]
                if ports:
                    port = int(ports[0].split()[1])
                    break
                time.sleep(.1)
            else:
                raise RuntimeError('Child did not start within 60 seconds')
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(f'http://127.0.0.1:{port}/health', timeout=2) as response:
                json.load(response)
            record['before'] = memory()
            start = time.monotonic()
            thread = threading.Thread(target=sampler)
            thread.start()
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as pool:
                results = list(pool.map(request, range(args.parallel)))
            time.sleep(2)
            record['held'] = memory()
            for conn in connections:
                conn.close()
            time.sleep(2)
            record['after'] = memory()
            if len({r['token_sha'] for r in results}) != 1 or len({r['content_sha256'] for r in results}) != 1:
                raise RuntimeError('Identical scripts returned different tokens or content')
            if args.max_rss_mib and record['after']['VmHWM'] > args.max_rss_mib * 2**20:
                raise RuntimeError('Peak RSS exceeded the regression ceiling')
            record['status'] = 'passed'
        except BaseException as exc:
            record.update(status='failed', error=type(exc).__name__ + ': ' + str(exc))
            raise
        finally:
            stop.set()
            if thread:
                thread.join()
            for conn in connections:
                conn.close()
            record.update(results=results, samples=samples, sample_errors=sample_errors, elapsed_s=time.monotonic()-start)
            if sample_errors:
                record.update(status='failed', error='Memory sampler failed: ' + '; '.join(sample_errors))
            if samples:
                record['peak_sample'] = max(samples, key=lambda x: x['anonymous_plus_swap'])
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            (args.output/'report.json').write_text(json.dumps(record, indent=2)+'\n')
    if sample_errors:
        raise RuntimeError('Memory sampler failed: ' + '; '.join(sample_errors))
    print(json.dumps({k: record[k] for k in ('status', 'before', 'held', 'after', 'peak_sample', 'elapsed_s')}, indent=2))


if __name__ == '__main__':
    main()
