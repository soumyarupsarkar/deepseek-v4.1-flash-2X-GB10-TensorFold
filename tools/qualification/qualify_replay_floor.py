"""Cold synthetic replay-boundary probes in different request orders.

Retained checkpoints are displaced between passes. Each measured request must
report zero cached tokens; receipts retain full token SHA256s, never token lists.
"""
import argparse
import hashlib
import json
import random
import re


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--record', required=True)
    p.add_argument('--chunk', type=int, choices=(1024, 2048), default=1024)
    p.add_argument('--reply-tokens', type=int, default=64)
    a = p.parse_args()
    assert re.fullmatch('[a-z0-9-]+', a.record) and 16 <= a.reply_tokens <= 256
    from common import API_BASE, PAIR, ROOT, atomic, now
    from cluster import get
    from qualify import post
    from benchmark import evict, prompt
    from memory_watch import health_sample
    before = get('/health')
    assert before['ok'] and not before['requests_running'] and not before.get('busy')
    launch = json.loads((PAIR.state/'launch.json').read_text())
    assert int(launch['profile']['environment']['TF_DS_PREFILL_CHUNK']) == a.chunk
    path = ROOT/('records/validation-'+a.record+'-replay-floor.json')
    assert not path.exists(), 'Preserve previous receipts'
    lengths = [k*a.chunk+tail for k in (2, 4) for tail in (2, 16, 111, 112, 120, 127, 128)]
    reference = {}
    record = dict(status='running', started=now(), parameters=vars(a), image=launch['image'],
                  containers=launch['containers'], passes=[], health_before=health_sample(before))
    atomic(path, record)
    try:
        shuffled = list(range(len(lengths)))
        random.Random(342).shuffle(shuffled)
        for turn, order in enumerate((list(range(len(lengths))), list(reversed(range(len(lengths)))), shuffled)):
            item = dict(order=order, results=[], eviction=evict(API_BASE, 34200+turn))
            record['passes'].append(item)
            # Change the last unrelated request as well as the probe order.
            poison, _ = prompt(API_BASE, 8192, 998000+turn)
            post(dict(prompt=poison, max_tokens=8, temperature=0, draft=False), '/v1/completions')
            for case in order:
                ids, _ = prompt(API_BASE, lengths[case], 534200+case)
                result = post(dict(prompt=ids, max_tokens=a.reply_tokens, temperature=0, seed=342+case,
                                   ignore_eos=True, draft=False, return_token_ids=True), '/v1/completions')
                response = result['response']
                usage, stats = response['usage'], response['tensorfold']
                tokens = stats.get('token_ids')
                cached = usage.get('prompt_tokens_details', {}).get('cached_tokens')
                assert cached == 0, ('not a cold replay probe', case, cached)
                assert usage['prompt_tokens'] == lengths[case] and usage['completion_tokens'] == a.reply_tokens
                assert isinstance(tokens, list) and len(tokens) == a.reply_tokens
                digest = hashlib.sha256(json.dumps(tokens, separators=(',', ':')).encode()).hexdigest()
                row = dict(case=case, prompt_tokens=lengths[case], cached_tokens=cached,
                           completion_tokens=len(tokens), token_ids_sha256=digest, seconds=result['seconds'])
                item['results'].append(row)
                atomic(path, record)
                if turn == 0:
                    reference[case] = digest
                else:
                    assert digest == reference[case], ('request-order replay changed', turn, case, lengths[case])
            print('replay order', turn, 'passed', len(order), 'cold probes', flush=True)
        health = get('/health')
        assert health['ok'] and not health['requests_running'] and not health.get('fatal')
        for key in ('allocation_ooms', 'allocation_retries', 'round_graph_captures'):
            assert health['memory'][key] == before['memory'][key], key+' changed'
        for host in ('head', 'worker'):
            rows = PAIR.containers(host)
            assert len(rows) == 1 and rows[0]['Id'] == launch['containers'][host] and rows[0]['State']['Running']
        record.update(status='passed', health_after=health_sample(health))
    except (KeyboardInterrupt, SystemExit) as exc:
        record.update(status='interrupted', error=type(exc).__name__+': '+str(exc))
        raise
    except BaseException as exc:
        record.update(status='failed', error=type(exc).__name__+': '+str(exc))
        raise
    finally:
        record['finished'] = now()
        atomic(path, record)


if __name__ == '__main__':
    main()
