"""Bounded live checks for seed policy, replay and coexistence with caching/drafting/constraints."""

import argparse
import concurrent.futures
import hashlib
import json
import re

from common import ROOT, atomic, now
from cluster import get
from qualify import post, stream_post, text


def seed(result):
    value = result['response']['tensorfold']['sampling_seed']
    assert value is None or isinstance(value, str), 'seed metadata must preserve integer precision'
    return None if value is None else int(value)


def token_hash(result):
    return result['response']['tensorfold']['token_sha']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('prompt', 'random'), default='random')
    parser.add_argument('--record', default=None)
    args = parser.parse_args()
    name=args.record or 'sampling-'+args.mode
    assert re.fullmatch('[a-z0-9-]+',name)
    record = dict(started=now(), mode=args.mode, health_before=get('/health'))
    body = dict(messages=[{'role': 'user', 'content':
        'Invent three unusual names for a tiny bookstore on a moon. Return only the three names.'}],
        max_tokens=64, temperature=1.0, chat_template_kwargs={'enable_thinking': False}, return_token_ids=True)
    try:
        record['unseeded'] = [post(body) for _ in range(4)]
        record['null_seed'] = post({**body, 'seed': None})
        seeds = [seed(r) for r in [*record['unseeded'], record['null_seed']]]
        assert all(s is not None and 0 <= s < 2**63 for s in seeds)
        if args.mode == 'random':
            assert len(set(seeds)) == len(seeds), 'requests did not receive fresh seeds'
        else:
            ids = post(body, '/tokenize')['response']['tokens']
            expected = int.from_bytes(hashlib.sha256((','.join(map(str, ids))+'|0').encode()).digest()[:8], 'little') & (2**63-1)
            assert set(seeds) == {expected}, 'prompt mode differs from the original default salt/seed'
            assert len({token_hash(r) for r in record['unseeded']}) == 1
        record['unique_unseeded_replies'] = len({token_hash(r) for r in record['unseeded']})
        record['replay'] = post({**body, 'seed': str(seeds[0])})
        assert token_hash(record['replay']) == token_hash(record['unseeded'][0])
        print('Unseeded/null requests and returned-seed replay passed', flush=True)

        fixed = {**body, 'seed': 0}
        record['seed_zero'] = post(fixed)
        assert seed(record['seed_zero']) == 0
        record['serial'] = post({**fixed, 'draft': False})
        assert token_hash(record['serial']) == token_hash(record['seed_zero'])
        record['stream'] = stream_post(fixed)
        assert record['stream']['tensorfold']['sampling_seed'] == '0'
        assert record['stream']['tensorfold']['token_sha'] == token_hash(record['seed_zero'])
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            record['concurrent'] = list(executor.map(lambda _: post(fixed), range(4)))
        assert all(seed(r) == 0 and token_hash(r) == token_hash(record['seed_zero']) for r in record['concurrent'])
        record['greedy'] = [post({**body, 'temperature': 0}) for _ in range(2)]
        assert all(seed(r) is None for r in record['greedy'])
        assert token_hash(record['greedy'][0]) == token_hash(record['greedy'][1])
        print('Explicit zero, draft/serial, streaming, concurrent/solo and greedy checks passed', flush=True)

        reference = '\n'.join(f'Item {i}: the blue compass points north.' for i in range(600))
        cached_body = {**body, 'messages': [{'role': 'user', 'content':
            'Seed-policy cache probe. Reference notes:\n'+reference+'\nInvent three names for this compass.'}]}
        record['cache_first'] = post(cached_body)
        record['cache_reuse'] = post(cached_body)
        usage = record['cache_reuse']['response']['usage']
        assert usage.get('prompt_tokens_details', {}).get('cached_tokens', 0) > 0, usage
        if args.mode == 'random':
            assert seed(record['cache_first']) != seed(record['cache_reuse'])
        record['cache_replay'] = post({**cached_body, 'seed': str(seed(record['cache_first']))})
        assert token_hash(record['cache_replay']) == token_hash(record['cache_first'])
        schema = {'type': 'object', 'properties': {'color': {'type': 'string', 'enum': ['blue', 'green', 'red']}},
                  'required': ['color'], 'additionalProperties': False}
        record['schema'] = post({**body, 'messages': [{'role': 'user', 'content': 'Choose a color and return JSON.'}],
            'response_format': {'type': 'json_schema', 'json_schema': {'name': 'color', 'strict': True, 'schema': schema}}})
        value = json.loads(text(record['schema']))
        assert set(value) == {'color'} and value['color'] in ('blue', 'green', 'red')
        assert seed(record['schema']) is not None
        assert record['schema']['response']['tensorfold']['drafts'] is False
        record['health_after'] = get('/health')
        assert record['health_after']['ok']
        record['status'] = 'passed'
    except BaseException as exc:
        record.update(status='failed', error=type(exc).__name__+': '+str(exc),
                      response_body=getattr(exc, 'response_body', None))
        raise
    finally:
        record['finished'] = now()
        atomic(ROOT/f'records/validation-{name}.json', record)
    print('Seed policy validation passed; unique unseeded replies:', record['unique_unseeded_replies'], flush=True)


if __name__ == '__main__':
    main()
