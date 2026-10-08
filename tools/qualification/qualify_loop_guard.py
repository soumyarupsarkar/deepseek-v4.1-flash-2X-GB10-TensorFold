"""Paired smoke for opt-in guard coexistence; forced-loop tests use synthetic HTTP engines."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import re

from common import ROOT, atomic, now
from cluster import get
from qualify import post, stream_post, text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--record', required=True)
    args = parser.parse_args()
    assert re.fullmatch('[a-z0-9-]+', args.record)
    path = ROOT / ('records/validation-' + args.record + '.json')
    assert not path.exists(), 'Preserve prior evidence; choose a new record prefix.'
    record = dict(started=now(), health_before=get('/health'), cases=[])
    body = dict(messages=[{'role': 'user', 'content':
        'Review this Python function: def remember(x, items=[]): items.append(x); return items. '
        'Explain its bug and give a corrected function. Keep the answer concise.'}],
        temperature=0.6, seed=73, max_tokens=1536,
        chat_template_kwargs={'enable_thinking': True}, return_token_ids=True)
    try:
        for fields in ({}, {'loop_guard': False}, {'loop_guard': True}):
            result = post({**body, **fields})
            record['cases'].append(dict(fields=fields, result=result))
            atomic(path, record)
            assert text(result).strip(), 'non-looping code review should reach its answer'
            assert not result['response']['tensorfold'].get('loop_guard')
        hashes = [r['result']['response']['tensorfold']['token_sha'] for r in record['cases']]
        assert len(set(hashes)) == 1, 'enabling an unfired guard changed committed output'
        record['stream'] = stream_post({**body, 'loop_guard': True})
        assert record['stream']['tensorfold']['token_sha'] == hashes[0]
        assert record['stream']['tensorfold']['sampling_seed'] == '73'
        with ThreadPoolExecutor(4) as pool:
            record['concurrent'] = list(pool.map(lambda on: post({**body, 'loop_guard': on}),
                                               [True, False, True, False]))
        assert all(r['response']['tensorfold']['token_sha'] == hashes[0] for r in record['concurrent'])

        schema = {'type': 'object', 'properties': {'answer': {'type': 'integer', 'const': 42}},
                  'required': ['answer'], 'additionalProperties': False}
        record['budget_schema'] = post({**body, 'loop_guard': True, 'thinking_budget': 32,
            'messages': [{'role': 'user', 'content': 'Return answer 42 as JSON.'}],
            'response_format': {'type': 'json_schema', 'json_schema': {
                'name': 'answer', 'strict': True, 'schema': schema}}})
        assert json.loads(text(record['budget_schema'])) == {'answer': 42}
        assert not record['budget_schema']['response']['tensorfold'].get('loop_guard')
        record['nonthinking'] = post({**body, 'loop_guard': True,
            'chat_template_kwargs': {'enable_thinking': False}})
        assert text(record['nonthinking']).strip()
        assert not record['nonthinking']['response']['tensorfold'].get('loop_guard')

        record['health_after'] = get('/health')
        before, after = record['health_before'], record['health_after']
        assert after['ok'] and not after['requests_running']
        assert after['memory']['allocation_ooms'] == before['memory']['allocation_ooms'] == 0
        assert after['memory']['allocation_retries'] == before['memory']['allocation_retries']
        assert after['memory']['round_graph_captures'] == before['memory']['round_graph_captures']
        record.update(status='passed', scope='Real paired non-looping guard parity, streaming, concurrent '
                      'requests, schema/budget and non-thinking exclusions. This does not force a real-model loop.')
    except BaseException as exc:
        record.update(status='failed', error=type(exc).__name__ + ': ' + str(exc),
                      response_body=getattr(exc, 'response_body', None))
        raise
    finally:
        record['finished'] = now()
        atomic(path, record)
    print('Paired loop-guard coexistence checks passed', flush=True)


if __name__ == '__main__':
    main()
