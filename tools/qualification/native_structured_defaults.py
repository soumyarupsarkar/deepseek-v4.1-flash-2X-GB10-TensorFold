"""Check ordinary constrained defaults and explicit drafting at C32."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import time

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE/'tools/qualification'))
import common
from configuration import profile, read, source_revision, STATE
from engine_health import ready
from benchmark import wait_idle
from native_endurance import rank_epochs, validate_continuity
from qualify import post


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', required=True)
    args = parser.parse_args()
    assert args.record.replace('-', '').isalnum()
    assert common.PAIR.config['api']['bind'] == '127.0.0.1'
    path = common.ROOT/'records'/('validation-'+args.record+'.json')
    assert not path.exists()
    pair = common.PAIR
    launch = read(STATE/'launch.json')
    epochs = rank_epochs(pair, launch)
    record = dict(status='running', started=common.now(), source=source_revision(),
                  image=launch['image'], waves=[],
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())

    def idle():
        h, _ = wait_idle(common.API_BASE)
        assert ready(h, profile()) and h['max_batch_size'] == 32
        assert h['structured_drafts'] and h['structured_drafts_default'] is False
        return h

    def ask(index, mode, temperature):
        expected = dict(values=[index]*64)
        schema = dict(type='object', properties=dict(values=dict(type='array', minItems=64,
            maxItems=64, items=dict(type='integer', const=index))),
            required=['values'], additionalProperties=False)
        body = dict(messages=[dict(role='user', content=f'Report an array of 64 copies of the number {index}.')],
            max_tokens=512, temperature=temperature, seed=301031+index,
            chat_template_kwargs=dict(enable_thinking=False),
            response_format=dict(type='json_schema', json_schema=dict(name='values', strict=True, schema=schema)))
        if mode is not None:
            body['draft'] = mode
        r = post(body)['response']
        assert json.loads(r['choices'][0]['message']['content']) == expected
        assert r['tensorfold']['drafts'] is (mode is True)
        return dict(index=index, token_sha=r['tensorfold']['token_sha'], usage=r['usage'])

    try:
        for temperature in (0, 1):
            hashes = []
            for mode in (None, False, True):
                before = idle()
                wave = dict(temperature=temperature, mode='default' if mode is None else mode,
                            started=common.now(), peak_decoding=0)
                record['waves'].append(wave)
                common.atomic(path, record)
                with ThreadPoolExecutor(max_workers=32) as pool:
                    jobs = [pool.submit(ask, index, mode, temperature) for index in range(32)]
                    while not all(job.done() for job in jobs):
                        h = pair.get('/health')
                        assert ready(h, profile())
                        n = h['native']
                        wave['peak_decoding'] = max(wave['peak_decoding'], n['active_streams']-n['prefilling_streams'])
                        time.sleep(.25)
                    wave['results'] = [job.result() for job in jobs]
                after = idle()
                wave['draft_passes'] = after['native']['draft_passes']-before['native']['draft_passes']
                wave['finished'] = common.now()
                assert wave['peak_decoding'] == 32
                assert (wave['draft_passes'] > 0) if mode is True else (wave['draft_passes'] == 0)
                assert after['completed']['requests']-before['completed']['requests'] == 32
                hashes.append([r['token_sha'] for r in wave['results']])
                validate_continuity(pair, launch, epochs, read(STATE/'launch.json'), read(STATE/'active.json'))
                common.atomic(path, record)
                print('C32', temperature, wave['mode'], 'passed', flush=True)
            assert hashes[0] == hashes[1] == hashes[2]
        record.update(status='passed', requests=192, final_health=idle())
    except BaseException as exc:
        record.update(status='failed', error=type(exc).__name__+': '+str(exc))
        raise
    finally:
        record['finished'] = common.now()
        common.atomic(path, record)


if __name__ == '__main__':
    main()
