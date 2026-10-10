"""Require C32 overlap with distinct strict schemas and required tool grammars."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import sys
import time

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'tools/qualification'))
import common
from cluster import get
from configuration import profile, read, STATE
from engine_health import ready, busy
from qualify import post, text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', required=True)
    parser.add_argument('--temperature', type=float, choices=(0, 1), default=0)
    args = parser.parse_args()
    if not args.record.replace('-', '').isalnum():
        raise ValueError('Use a simple unique record name')
    path = common.ROOT / 'records' / ('validation-' + args.record + '.json')
    if path.exists() or common.PAIR.config['api']['bind'] != '127.0.0.1':
        raise RuntimeError('Use a new receipt and isolated loopback installation')
    config = profile()
    if config['parallel'] != 32:
        raise RuntimeError('This fixture qualifies C32')
    health = get('/health')
    if not ready(health, config) or busy(health):
        raise RuntimeError('Require an idle healthy candidate')
    record = dict(started=common.now(), status='running', launch=read(STATE / 'launch.json'),
                  temperature=args.temperature, waves=[])
    common.atomic(path, record)

    def request(index, mode):
        expected = {'values': [index] * 128}
        schema = dict(type='object', properties=dict(values=dict(type='array', minItems=128,
            maxItems=128, items={'const': index})), required=['values'], additionalProperties=False)
        body = dict(messages=[dict(role='user', content=f'Report an array of 128 copies of the number {index}.')],
                    temperature=args.temperature, seed=96000+index, max_tokens=1024,
                    chat_template_kwargs={'enable_thinking': False})
        if mode == 'schema':
            body['response_format'] = dict(type='json_schema', json_schema=dict(name='values', strict=True, schema=schema))
        else:
            body.update(tools=[dict(type='function', function=dict(name='report', strict=True, parameters=schema))],
                        tool_choice='required', parallel_tool_calls=False)
        result = post(body)
        if mode == 'schema':
            actual = json.loads(text(result))
        else:
            calls = result['response']['choices'][0]['message'].get('tool_calls', [])
            if len(calls) != 1 or calls[0]['function']['name'] != 'report':
                raise AssertionError('Required report tool missing')
            actual = json.loads(calls[0]['function']['arguments'])
        if actual != expected or result['response']['tensorfold']['drafts'] is not False:
            raise AssertionError('Strict per-request grammar differs or drafting bypassed its mask')
        return dict(index=index, seconds=result['seconds'], usage=result['response']['usage'],
                    token_sha=result['response']['tensorfold']['token_sha'], valid=True)

    try:
        for mode in ('schema', 'tools'):
            wave = dict(mode=mode, started=common.now(), peak_decoding=0, samples=[], results=[])
            record['waves'].append(wave)
            common.atomic(path, record)
            with ThreadPoolExecutor(max_workers=32) as pool:
                jobs = [pool.submit(request, index, mode) for index in range(32)]
                while not all(job.done() for job in jobs):
                    h = get('/health')
                    if not ready(h, config):
                        raise RuntimeError('Candidate became unhealthy')
                    n = h['native']
                    decoding = n['active_streams'] - n['prefilling_streams']
                    wave['peak_decoding'] = max(wave['peak_decoding'], decoding)
                    wave['samples'].append(dict(time=common.now(), decoding=decoding,
                        running=h['scheduler']['running'], waiting=h['scheduler']['waiting']))
                    time.sleep(.25)
                wave['results'] = [job.result() for job in jobs]
            wave['finished'] = common.now()
            common.atomic(path, record)
            if wave['peak_decoding'] != 32:
                raise AssertionError('Did not observe all 32 constrained requests decoding together')
            print(mode, 'passed at C32', flush=True)
        h = get('/health')
        if not ready(h, config) or busy(h):
            raise RuntimeError('Candidate did not return to healthy idle')
        record.update(status='passed', health_after=h)
    except BaseException as exc:
        record.update(status='failed', error=type(exc).__name__ + ': ' + str(exc))
        raise
    finally:
        record['finished'] = common.now()
        common.atomic(path, record)


if __name__ == '__main__':
    main()
