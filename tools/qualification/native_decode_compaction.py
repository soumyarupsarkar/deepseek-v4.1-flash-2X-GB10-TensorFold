"""Prove post-relocation decoder continuation, excluding buffered earlier text.

Synthetic loopback requests only. A uniform-reservation compaction reports how
many of eight surviving extents moved. Select 8 - moved + 1 survivors: at least
one selected stream must have moved. Cancel every other request, checkpoint the
selected streams' total generated tokens, and read more nonempty chunks than
that total plus 128. Each selected stream then includes post-checkpoint output,
even with one in-flight ordinary decode round. Compare each complete observed
prefix with a fresh solo stream. No per-request server diagnostic is required.
"""
import argparse
import hashlib
import http.client
import json
from pathlib import Path
import socket
import sys
import threading
import time
from urllib.parse import urlsplit


def witnesses(survivors, moved):
    if type(moved) is not int or not 1 <= moved <= len(survivors):
        raise ValueError('Require a positive, bounded relocation count')
    return survivors[:len(survivors) - moved + 1]


class Reader:
    """One owned SSE socket, pausable by its client and cancellable at any time."""
    def __init__(self, base, body, *, expected=None):
        address = urlsplit(base)
        if address.scheme != 'http' or address.hostname != '127.0.0.1':
            raise ValueError('Require a loopback candidate')
        self.connection = http.client.HTTPConnection(address.hostname, address.port, timeout=900)
        self.socket = None
        self.body = json.dumps(dict(body, stream=True), separators=(',', ':')).encode()
        self.expected = expected
        self.holding = threading.Event()
        self.release = threading.Event()
        self.stopping = threading.Event()
        self.done = threading.Event()
        self.parts = []
        self.characters = 0
        self.goal = None
        self.error = None
        self.started = None
        self.finished = None
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        self.started = time.monotonic()
        try:
            self.connection.connect()
            self.socket = self.connection.sock
            if self.stopping.is_set():
                return
            self.connection.request('POST', '/v1/completions', body=self.body,
                                    headers={'Content-Type': 'application/json'})
            with self.connection.getresponse() as response:
                if response.status != 200:
                    raise RuntimeError('Synthetic stream HTTP status ' + str(response.status))
                while True:
                    line = response.readline()
                    if not line or line.strip() == b'data: [DONE]':
                        raise AssertionError('Reserved holder ended before the bounded client read')
                    if self.stopping.is_set():
                        return
                    if not line.startswith(b'data:'):
                        continue
                    value = json.loads(line[5:].strip())
                    if 'error' in value:
                        raise AssertionError('Synthetic stream returned an error')
                    piece = ''.join(choice.get('text') or '' for choice in value.get('choices', []))
                    if not piece:
                        continue
                    self.parts.append(piece)
                    self.characters += len(piece)
                    if self.characters > 2**20:
                        raise RuntimeError('Bounded synthetic reply limit reached')
                    if self.expected is not None:
                        if self.characters >= len(self.expected):
                            if not ''.join(self.parts).startswith(self.expected):
                                raise AssertionError('Post-relocation continuation differs from solo')
                            return
                        continue
                    if len(self.parts) == 24:
                        self.holding.set()
                        if not self.release.wait(300):
                            raise TimeoutError('Coordinator did not release held synthetic stream')
                        if self.stopping.is_set():
                            return
                    if self.goal is not None and len(self.parts) >= self.goal:
                        return
        except BaseException as exc:
            if not self.stopping.is_set():
                self.error = exc
        finally:
            self.connection.close()
            self.finished = time.monotonic()
            self.done.set()

    def start(self):
        self.thread.start()
        return self

    def cancel(self):
        self.stopping.set()
        self.release.set()
        sock = self.socket
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.connection.close()

    def check(self):
        if self.error is not None:
            raise self.error

    def summary(self):
        self.check()
        return dict(chunks=len(self.parts), characters=self.characters,
                    text_sha256=hashlib.sha256(''.join(self.parts).encode()).hexdigest(),
                    seconds=self.finished-self.started)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installation', type=Path, default=Path.cwd())
    parser.add_argument('--record', required=True)
    args = parser.parse_args()
    if not args.record.replace('-', '').isalnum():
        raise ValueError('Require a unique record name')
    source = args.installation.resolve()
    sys.path.insert(0, str(source/'tools/qualification'))
    import common
    import cluster
    from benchmark import wait_idle
    from configuration import profile, read, STATE
    from engine_health import ready
    from qualify import MODEL, post
    assert common.PAIR.config['api']['bind'] == '127.0.0.1'
    path = common.ROOT/'records'/('validation-'+args.record+'.json')
    assert not path.exists(), 'Preserve earlier receipts'
    p = profile()
    assert p['pool_tokens'] == 8650752 and p['parallel'] == 32
    assert int(p['environment']['TF_DS_ROUND_ROWS']) == 48
    from compaction_fixture import condition
    conditioned = path.with_name(path.stem + '-conditioning.json')
    condition(common, conditioned)
    reservation = ((524288 + 48 + 2 + 2047)//2048)*2048
    record = dict(started=common.now(), status='running', launch=read(STATE/'launch.json'),
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  conditioning=dict(receipt=conditioned.name,
                      sha256=hashlib.sha256(conditioned.read_bytes()).hexdigest()),
                  reservation_tokens=reservation, samples=[], fixtures=[], phases=[])
    probes = []
    deadline = time.monotonic() + 1800

    def save():
        record['updated'] = common.now()
        common.atomic(path, record)

    def health():
        if time.monotonic() > deadline:
            raise TimeoutError('Decoder compaction qualification exceeded thirty minutes')
        value = cluster.get('/health')
        if not ready(value, p):
            raise RuntimeError('Owned native pair is unhealthy')
        record['samples'].append(dict(time=common.now(), native=value['native'], scheduler=value['scheduler']))
        if len(record['samples']) > 12000:
            raise RuntimeError('Health evidence bound reached')
        return value

    def wait_for(predicate, timeout=90):
        end = min(deadline, time.monotonic()+timeout)
        while time.monotonic() < end:
            for probe in probes:
                probe.check()
            value = health()
            if predicate(value):
                return value
            time.sleep(.2)
        raise TimeoutError('Synthetic relocation condition did not arrive')

    def start(body, expected=None):
        probe = Reader(common.API_BASE, body, expected=expected)
        probes.append(probe)
        return probe.start()

    save()
    try:
        initial = health()
        assert initial['scheduler']['running'] == 0 and initial['scheduler']['waiting'] == 0
        bodies = []
        for i in range(17):
            prompt = post(dict(messages=[{'role': 'user', 'content':
                f'Synthetic post-relocation decoder check {i}. Count upwards from 1, explaining each number in one sentence.'}],
                chat_template_kwargs={'enable_thinking': False}), '/tokenize')['response']['tokens']
            assert len(prompt) < 2048
            limit = 524288 if i < 16 else 1048576
            bodies.append(dict(model=MODEL, prompt=prompt, max_tokens=limit-len(prompt),
                               ignore_eos=True, temperature=0, draft=False,
                               chat_template_kwargs={'enable_thinking': False}))
            record['fixtures'].append(dict(index=i, prompt_tokens=len(prompt), reservation_window=limit,
                prompt_sha256=hashlib.sha256(json.dumps(prompt, separators=(',', ':')).encode()).hexdigest()))
        holders = []
        for i in range(16):
            holder = start(bodies[i])
            holders.append(holder)
            wait_for(lambda _h: holder.holding.is_set())
        full = health()
        assert full['native']['active_streams'] == 16 and full['native']['prefilling_streams'] == 0
        assert full['native']['compactions'] == initial['native']['compactions'], \
            'Initial placement compacted; alternating arrival indices no longer prove fragmentation'
        record['phases'].append(dict(name='full-uniform-reservations', health=full))
        save()
        for i in range(0, 16, 2):
            holders[i].cancel()
        fragmented = wait_for(lambda h: h['native']['active_streams'] == 8 and h['scheduler']['running'] == 8)
        extra = start(bodies[16])
        wait_for(lambda _h: extra.holding.is_set())
        relocated = health()
        assert relocated['native']['compactions'] - fragmented['native']['compactions'] == 1
        delta = relocated['native']['relocated_tokens'] - fragmented['native']['relocated_tokens']
        assert delta > 0 and delta % reservation == 0
        moved = delta//reservation
        selected = witnesses(list(range(1, 16, 2)), moved)
        record['moved_survivors'] = moved
        record['selected_survivors'] = selected
        record['selection_proof'] = 'Selected count exceeds the total number of unmoved survivors; at least one selected stream relocated.'
        record['phases'].append(dict(name='relocation', before=fragmented, after=relocated))
        for i, holder in enumerate(holders):
            if i not in selected:
                holder.cancel()
        extra.cancel()
        checkpoint = wait_for(lambda h: h['native']['active_streams'] == len(selected)
            and h['scheduler']['running'] == len(selected) and h['scheduler']['waiting'] == 0)
        assert checkpoint['native']['prefilling_streams'] == 0
        generated = checkpoint['scheduler']['generation_tokens_running']
        assert type(generated) is int and 0 <= generated <= 8192
        # Health's aggregate is an upper bound on each selected stream. Allow
        # more than one complete 48-row round beyond its last scheduler sample.
        required = generated + 128
        record['post_relocation_checkpoint'] = dict(health=checkpoint,
            selected_generated_tokens=generated, required_nonempty_chunks_each=required,
            round_slack_tokens=64, minimum_post_checkpoint_tokens_each=64)
        save()
        for i in selected:
            holders[i].goal = required
            holders[i].release.set()
        wait_for(lambda _h: all(holders[i].done.is_set() for i in selected), timeout=900)
        record['continued'] = [dict(index=i, **holders[i].summary()) for i in selected]
        assert all(row['chunks'] >= required for row in record['continued'])
        record['post_continuation_idle'], record['post_continuation_drain'] = wait_idle(common.API_BASE, timeout=30)
        record['solo_comparisons'] = []
        for i in selected:
            expected = ''.join(holders[i].parts)
            solo = start(bodies[i], expected=expected)
            wait_for(lambda _h: solo.done.is_set(), timeout=900)
            record['solo_comparisons'].append(dict(index=i, prefix_equal=True, **solo.summary()))
            wait_idle(common.API_BASE, timeout=30)
            save()
        record['health_after'], record['drain'] = wait_idle(common.API_BASE, timeout=30)
        record['status'] = 'passed'
    except BaseException as exc:
        record.update(status='failed', error=type(exc).__name__+': '+str(exc))
        raise
    finally:
        for probe in probes:
            probe.cancel()
        end = time.monotonic()+30
        for probe in probes:
            probe.thread.join(timeout=max(0, end-time.monotonic()))
        if any(probe.thread.is_alive() for probe in probes):
            record.update(status='failed', cleanup_error='Owned synthetic reader did not stop')
        record['finished'] = common.now()
        save()
        if record.get('cleanup_error'):
            raise RuntimeError(record['cleanup_error'])
    print('Post-relocation decoder continuation and solo-prefix parity passed', flush=True)


if __name__ == '__main__':
    main()
