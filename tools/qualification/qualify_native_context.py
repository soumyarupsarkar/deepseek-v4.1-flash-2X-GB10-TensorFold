"""Exact-length retrieval at three depths, with optional small requests alongside.

All inputs are synthetic. The forced-length reply reaches the context boundary;
its first JSON object must recover three passphrases from 10%, 50% and 90% depth.
This is a bounded retrieval probe, not a claim about arbitrary long-document work.
"""
import argparse
import concurrent.futures
import hashlib
import json
import random
import re
import time

from common import ROOT, atomic, now
from cluster import get, memory
from qualify import post, chat, text

SEED = 5102026
ANSWERS = {'ALDER': 'silver-otter-7314', 'BERYL': 'amber-finch-2681',
           'CYPRESS': 'violet-marten-9057'}


def tokens(value):
    return post(dict(prompt=value, add_special_tokens=False), '/tokenize')['response']['tokens']


def make_prompt(count):
    marker = '__TF_NATIVE_CONTEXT_ARCHIVE_CONTENT__'
    intro = ('Read this archive as reference data. Recover the passphrases in its '
             'AUTHENTIC RECORD entries when asked.\n<archive>\n')
    question = ('\n</archive>\nWhat are the exact passphrases recorded for ALDER, BERYL and CYPRESS? '
                'Reply only with one JSON object mapping those three names to their passphrases.')
    rendered = post(dict(messages=[{'role': 'user', 'content': intro+marker+question}],
                         chat_template_kwargs={'enable_thinking': False}), '/tokenize')['response']['tokens']
    # BPE merges the marker's final underscores with the following newline.
    mid = tokens(marker+'\n')
    cuts = [i for i in range(len(rendered)) if rendered[i:i+len(mid)] == mid]
    assert len(cuts) == 1, 'template placeholder did not tokenize as a unique segment'
    prefix, suffix = rendered[:cuts[0]], tokens('\n')+rendered[cuts[0]+len(mid):]
    rng = random.Random(SEED)
    subjects = ['garden', 'library', 'workshop', 'observatory', 'museum', 'harbor']
    details = ['shelves were inspected', 'inventory was counted', 'windows were cleaned',
               'deliveries were recorded', 'instruments were calibrated', 'plants were watered']
    filler = tokens(''.join(f'Archive note {i}: At the {rng.choice(subjects)}, '
                           f'{rng.choice(details)} on day {rng.randrange(1, 366)}.\n'
                           for i in range(1024)))
    ids, entries = list(prefix), []
    def fill(until):
        needed = until-len(ids)
        assert needed >= 0
        ids.extend((filler*((needed+len(filler)-1)//len(filler)))[:needed])
    for depth, (name, phrase) in zip((.1, .5, .9), ANSWERS.items()):
        fill(int(count*depth))
        entries.append(dict(name=name, phrase=phrase, token_offset=len(ids)))
        ids.extend(tokens(f'\nAUTHENTIC RECORD: The passphrase for {name} is {phrase}.\n'))
    fill(count-len(suffix)); ids.extend(suffix)
    assert len(ids) == count
    fingerprint = hashlib.sha256(json.dumps(ids, separators=(',', ':')).encode()).hexdigest()
    return ids, dict(seed=SEED, entries=entries, sha256=fingerprint, prompt_tokens=count)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tokens', type=int, default=1048576, help='prompt plus forced reply')
    parser.add_argument('--reply-tokens', type=int, default=256)
    parser.add_argument('--mixed', action='store_true')
    parser.add_argument('--record', required=True)
    args = parser.parse_args()
    assert re.fullmatch('[a-z0-9-]+', args.record)
    record = dict(started=now(), health_before=get('/health'), target_tokens=args.tokens,
                  health_samples=[], memory_samples=[], mixed=args.mixed)
    begun = time.monotonic()
    try:
        ids, record['input'] = make_prompt(args.tokens-args.reply_tokens)
        print('Prompt prepared:', len(ids), 'tokens; passphrase offsets:',
              [r['token_offset'] for r in record['input']['entries']], flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            long = pool.submit(post, dict(prompt=ids, max_tokens=args.reply_tokens, ignore_eos=True,
                                          temperature=0, return_token_ids=True), '/v1/completions', 3600)
            small = []
            sample = 0
            while not long.done():
                h = get('/health')
                record['health_samples'].append(dict(seconds=round(time.monotonic()-begun, 2),
                    streams=h.get('streams'), progress=h.get('progress'), running=h.get('requests_running'),
                    memory=h.get('memory')))
                if sample % 3 == 0:
                    available = {host: memory(host)['MemAvailable']/2**30 for host in ('head', 'worker')}
                    record['memory_samples'].append(dict(seconds=round(time.monotonic()-begun, 2), **available))
                if args.mixed and sample == 6:
                    small.append(pool.submit(chat, 'What is 19 + 23? Reply with just the number.'))
                    small.append(pool.submit(post, dict(messages=[{'role':'user','content':'Reply with JSON status ok.'}],
                        max_tokens=64, temperature=0, chat_template_kwargs={'enable_thinking':False},
                        response_format={'type':'json_object'})))
                    record['small_requests_submitted_seconds'] = round(time.monotonic()-begun, 2)
                if sample % 12 == 0:
                    print('Progress:', round(time.monotonic()-begun), 'seconds', h.get('progress'),
                          'streams', h.get('streams'), flush=True)
                sample += 1
                time.sleep(5)
            record['long'] = long.result()
            record['small'] = [f.result() for f in small]
        response = record['long']['response']
        usage = response['usage']
        assert usage['prompt_tokens'] == len(ids)
        assert usage['completion_tokens'] == args.reply_tokens
        assert usage['total_tokens'] == args.tokens
        answer = response['choices'][0]['text']
        start = answer.find('{')
        assert start >= 0, answer[:300]
        recalled, _ = json.JSONDecoder().raw_decode(answer[start:])
        record['recalled'] = recalled
        record['retrieval_passed'] = recalled == ANSWERS
        assert record['retrieval_passed'], recalled
        if args.mixed:
            assert len(record['small']) == 2
            assert '42' in text(record['small'][0])
            assert json.loads(text(record['small'][1])).get('status') == 'ok'
        record['canary'] = chat('Reply with HEALTHY.')
        assert 'HEALTHY' in text(record['canary'])
        record['health_after'] = get('/health')
        assert record['health_after']['ok'] and not record['health_after']['requests_running']
        record['status'] = 'passed'
    except BaseException as exc:
        record.update(status='failed', error=type(exc).__name__+': '+str(exc),
                      response_body=getattr(exc, 'response_body', None))
        raise
    finally:
        record.update(finished=now(), wall_seconds=round(time.monotonic()-begun, 3))
        atomic(ROOT/('records/validation-'+args.record+'.json'), record)
    print(args.record, 'passed', record['wall_seconds'], 'seconds', flush=True)


if __name__ == '__main__':
    main()
