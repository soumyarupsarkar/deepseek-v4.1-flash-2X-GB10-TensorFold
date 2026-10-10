"""Bounded synthetic checks of incremental prefill, image switching and cancellation.

All sockets belong to requests created here. A failed check closes those sockets
and preserves its receipt; it does not stop or restart either serving rank.
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

SOURCE = Path(__file__).resolve().parents[2]


class Probe:
    """One owned HTTP request whose socket can be closed during prompt loading."""

    def __init__(self, base, body, route='/v1/chat/completions'):
        address = urlsplit(base)
        if address.scheme != 'http' or address.hostname != '127.0.0.1':
            raise ValueError('Require an isolated loopback candidate')
        self.connection = http.client.HTTPConnection(address.hostname, address.port, timeout=1800)
        self.socket = None
        self.abort = threading.Event()
        self.body = json.dumps(body, separators=(',', ':')).encode()
        self.route = route
        self.done = threading.Event()
        self.result = None
        self.error = None
        self.started = None
        self.finished = None
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        self.started = time.monotonic()
        try:
            self.connection.connect()
            self.socket = self.connection.sock
            if self.abort.is_set():
                raise ConnectionAbortedError('Synthetic request cancelled before submission')
            self.connection.request('POST', self.route, body=self.body,
                                    headers={'Content-Type': 'application/json'})
            with self.connection.getresponse() as response:
                value = json.load(response)
                if response.status != 200 or 'error' in value:
                    raise RuntimeError('Synthetic request failed: ' + str(value))
            self.result = dict(seconds=time.monotonic() - self.started, response=value)
        except BaseException as exc:
            self.error = exc
        finally:
            self.finished = time.monotonic()
            self.connection.close()
            self.done.set()

    def start(self):
        self.thread.start()
        return self

    def answer(self):
        if not self.done.is_set():
            raise RuntimeError('Request has not finished')
        if self.error is not None:
            raise self.error
        return self.result

    def close(self):
        self.abort.set()
        sock = self.socket
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.connection.close()
        self.thread.join(timeout=30)
        if self.thread.is_alive():
            raise RuntimeError('Owned synthetic request did not terminate after socket shutdown')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', required=True)
    parser.add_argument('--seed', type=int, default=2026101100)
    parser.add_argument('--latency-limit', type=float, default=30)
    args = parser.parse_args()
    if not args.record.replace('-', '').isalnum() or not 0 < args.latency_limit <= 30:
        raise ValueError('Use a unique record name and a latency limit of at most 30 seconds')
    sys.path.insert(0, str(SOURCE / 'tools/qualification'))
    import common
    from benchmark import prompt, wait_idle
    from cluster import get
    from configuration import profile, read, STATE
    from engine_health import ready, busy
    from qualify import MODEL, post, text, png

    path = common.ROOT / 'records' / ('validation-' + args.record + '.json')
    if path.exists() or common.PAIR.config['api']['bind'] != '127.0.0.1':
        raise RuntimeError('Require a new receipt and loopback installation')
    health = get('/health')
    if not ready(health, profile()) or busy(health):
        raise RuntimeError('Require a healthy idle candidate')
    record = dict(status='running', started=common.now(), launch=read(STATE / 'launch.json'),
                  seed=args.seed, latency_limit_s=args.latency_limit, samples=[], stages=[],
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    probes = []

    def save():
        record['updated'] = common.now()
        common.atomic(path, record)

    def health_sample():
        value = get('/health')
        if not ready(value, profile()):
            raise RuntimeError('Candidate became unhealthy')
        record['samples'].append(dict(time=common.now(), native=value['native'], scheduler=value['scheduler']))
        return value

    def start(body, route='/v1/chat/completions'):
        probe = Probe(common.API_BASE, dict(model=MODEL, **body), route)
        probes.append(probe)
        return probe.start()

    def wait_for(predicate, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = health_sample()
            if predicate(value):
                return value
            time.sleep(.25)
        raise TimeoutError('Synthetic prefill condition did not arrive within its bound')

    def filling(probe, baseline):
        value = wait_for(lambda h: probe.done.is_set() or (
            h['native']['prefilling_streams'] > 0 and h['native']['prefill_tokens'] >= baseline + 2048), 60)
        if probe.done.is_set():
            probe.answer()
            raise AssertionError('Long request ended before partial prefill was observed')
        return value

    def image_body(color, reference=''):
        return dict(messages=[{'role': 'user', 'content': [
            {'type': 'text', 'text': reference + '\nWhat color is the large square? Answer with just the color name.'},
            {'type': 'image_url', 'image_url': {'url': png(color)}}]}], max_tokens=32, temperature=0,
            chat_template_kwargs={'enable_thinking': False}, return_token_ids=True)

    save()
    try:
        ids, _ = prompt(common.API_BASE, 262144, args.seed, 'code')
        baseline = health_sample()['native']['prefill_tokens']
        long_body = dict(prompt=ids, max_tokens=256, ignore_eos=True, temperature=0, return_token_ids=True)
        long = start(long_body, '/v1/completions')
        filling(long, baseline)
        schema = dict(type='object', properties={'status': {'const': 'ok'}, 'value': {'const': 42}},
                      required=['status', 'value'], additionalProperties=False)
        small_bodies = [
            dict(messages=[{'role': 'user', 'content': 'What is 19 + 23? Reply with just the number.'}],
                 max_tokens=32, temperature=0, chat_template_kwargs={'enable_thinking': False}),
            dict(messages=[{'role': 'user', 'content': 'Return status ok and value 42 as JSON.'}],
                 max_tokens=64, temperature=0, chat_template_kwargs={'enable_thinking': False},
                 response_format={'type': 'json_schema', 'json_schema': {'name': 'prefill', 'strict': True, 'schema': schema}}),
            image_body((240, 20, 20)), image_body((20, 20, 240)),
            dict(messages=[{'role': 'user', 'content':
                'Give three concise improvements for a Python function that appends an item to a mutable default list.'}],
                max_tokens=96, temperature=1, seed=73, return_token_ids=True,
                chat_template_kwargs={'enable_thinking': False}),
        ]
        submitted = time.monotonic()
        small = [start(body) for body in small_bodies]
        while not all(probe.done.is_set() for probe in small):
            if time.monotonic() - submitted >= args.latency_limit:
                raise TimeoutError('Small requests exceeded the declared latency bound during long prefill')
            if long.done.is_set():
                raise AssertionError('Long request finished before the small requests')
            health_sample()
            time.sleep(.1)
        replies = [probe.answer() for probe in small]
        after_small = health_sample()
        if after_small['native']['prefilling_streams'] != 1 or long.done.is_set():
            raise AssertionError('Small requests did not finish while the long request was still prefilling')
        assert '42' in text(replies[0])
        assert json.loads(text(replies[1])) == {'status': 'ok', 'value': 42}
        assert 'red' in text(replies[2]).lower() and 'blue' in text(replies[3]).lower()
        assert text(replies[4]).strip()
        record['stages'].append(dict(name='small-requests-during-cold-prefill', replies=replies,
                                    health=after_small, small_wall_seconds=time.monotonic() - submitted))
        save()
        wait_for(lambda _h: long.done.is_set(), 1800)
        result = long.answer()
        assert result['response']['usage']['prompt_tokens_details']['cached_tokens'] == 0
        replay = post(long_body, '/v1/completions', timeout=1800)
        assert result['response']['tensorfold']['token_sha'] == replay['response']['tensorfold']['token_sha']
        assert replay['response']['usage']['prompt_tokens_details']['cached_tokens'] > 0
        record['stages'].append(dict(name='interleaved-long-vs-cached-solo', interleaved=result, replay=replay))
        sampled_solo = post(small_bodies[4])
        assert replies[4]['response']['tensorfold']['token_sha'] == sampled_solo['response']['tensorfold']['token_sha']
        record['stages'].append(dict(name='sampled-short-interleaved-vs-solo', interleaved=replies[4], solo=sampled_solo))
        wait_idle(common.API_BASE)

        # A second image arrives after the first image prompt has consumed chunks.
        # Their token layouts match; their pixels and required answers differ.
        reference = ''.join(f'Synthetic image-switch note {i}: shelf {(i * 73) % 101} was inspected.\n'
                            for i in range(800))
        red_body = image_body((240, 20, 20), reference)
        baseline = health_sample()['native']['prefill_tokens']
        red = start(red_body)
        filling(red, baseline)
        blue = start(image_body((20, 20, 240)))
        image_switch = wait_for(lambda _h: blue.done.is_set(), args.latency_limit)
        assert not red.done.is_set() and image_switch['native']['prefilling_streams'] == 1, \
            'Short image request did not complete during the other image prompt prefill'
        wait_for(lambda _h: red.done.is_set(), 180)
        red_result, blue_result = red.answer(), blue.answer()
        assert 'red' in text(red_result).lower() and 'blue' in text(blue_result).lower()
        red_solo = post(red_body)
        assert red_result['response']['tensorfold']['token_sha'] == red_solo['response']['tensorfold']['token_sha']
        assert red_result['response']['usage']['prompt_tokens_details']['cached_tokens'] == 0
        assert red_solo['response']['usage']['prompt_tokens_details']['cached_tokens'] == 0
        record['stages'].append(dict(name='image-switch-and-solo-parity', red=red_result, blue=blue_result,
                                    solo=red_solo, health_at_blue_finish=image_switch))
        wait_idle(common.API_BASE)

        # Cancel before the first generated token; a synthetic socket shutdown is
        # the trigger, and the owned pair must become idle without a restart.
        cancel_ids, _ = prompt(common.API_BASE, 262144, args.seed + 1, 'prose')
        cancellation_cases = [
            ('text', dict(prompt=cancel_ids, max_tokens=256, ignore_eos=True, temperature=0),
             '/v1/completions', len(cancel_ids)),
            ('image', red_body, '/v1/chat/completions', red_result['response']['usage']['prompt_tokens']),
        ]
        for name, body, route, count in cancellation_cases:
            baseline = health_sample()['native']['prefill_tokens']
            cancelled = start(body, route)
            before_cancel = filling(cancelled, baseline)
            cancelled.close()
            after_cancel, drain = wait_idle(common.API_BASE, timeout=30)
            assert after_cancel['native']['prefill_tokens'] - baseline < count, \
                'Cancellation did not stop the prompt before prefill completed'
            canary = post(image_body((20, 20, 240)))
            assert 'blue' in text(canary).lower()
            record['stages'].append(dict(name='cancel-partially-filled-' + name, before=before_cancel,
                after=after_cancel, drain=drain, canary=canary,
                client_error=None if cancelled.error is None else type(cancelled.error).__name__))
            wait_idle(common.API_BASE)
            save()
        record['health_after'], record['post_response_drain'] = wait_idle(common.API_BASE)
        record['status'] = 'passed'
    except BaseException as exc:
        record.update(status='failed', error=type(exc).__name__ + ': ' + str(exc))
        raise
    finally:
        cleanup = []
        for probe in probes:
            try:
                probe.close()
            except Exception as exc:
                cleanup.append(type(exc).__name__ + ': ' + str(exc))
        if cleanup:
            record.update(status='failed', cleanup_errors=cleanup)
        record['finished'] = common.now()
        save()
        if cleanup:
            raise RuntimeError('Synthetic client cleanup was incomplete')
    print('Incremental prefill, image switching, prefix replay and partial cancellation passed', flush=True)


if __name__ == '__main__':
    main()
