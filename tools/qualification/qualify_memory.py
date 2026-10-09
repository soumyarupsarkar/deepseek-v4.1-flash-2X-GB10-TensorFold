"""Repeat growing histories at concurrency; capture live memory, never user content."""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import threading
import time

from common import ROOT, atomic, now
from cluster import get, memory
from qualify import post, text, vision
from qualify_pool import prompt_ids


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--record', required=True)
    parser.add_argument('--mode', choices=['raw', 'tools'], default='raw')
    parser.add_argument('--streams', type=int, default=16)
    parser.add_argument('--rounds', type=int, default=8)
    parser.add_argument('--initial-tokens', type=int, default=16384)
    parser.add_argument('--growth', type=int, default=2048)
    parser.add_argument('--reply-tokens', type=int, default=384)
    parser.add_argument('--shared-prefix', action='store_true',
                        help='Prime one shared document so all histories can reuse it at once (raw mode)')
    parser.add_argument('--identical', action='store_true',
                        help='Use exactly the same prompt on every stream (with --shared-prefix)')
    parser.add_argument('--prime-offset', type=int, default=0,
                        help='Extra tokens in the priming document (0 preserves the nearest matching checkpoint)')
    parser.add_argument('--require-concurrency',action='store_true',
                        help='Require all requested streams to be observed decoding in every cycle')
    parser.add_argument('--no-draft',action='store_true',help='Compare ordinary decoding for raw full-session requests')
    parser.add_argument('--require-replay-parity', action='store_true',
                        help='Require identical token IDs by fixed seed across identical, non-growing raw waves')
    parser.add_argument('--require-compaction', action='store_true',
                        help='Require this workload to exercise live KV relocation at least once')
    args = parser.parse_args()
    assert re.fullmatch('[a-z0-9-]+',args.record)
    assert not args.shared_prefix or args.mode=='raw'
    assert not args.identical or args.shared_prefix
    assert not args.no_draft or args.mode=='raw'
    assert not args.require_replay_parity or (args.identical and args.growth == 0 and args.rounds >= 2)
    path = ROOT / ('records/validation-' + args.record + '.json')
    assert not path.exists(), 'Choose a new receipt name; preserve the comparison.'
    record = dict(started=now(), contract_version=2, parameters=vars(args), health_before=get('/health'),
                  active=json.loads((ROOT/'records/active.json').read_text()), cycles=[], samples=[])
    started = time.monotonic()
    done = threading.Event()

    def monitor():
        next_hosts = 0
        while not done.is_set():
            sample = dict(seconds=round(time.monotonic() - started, 2))
            try:
                rss = next(line.split()[1] for line in Path('/proc/self/status').read_text().splitlines()
                           if line.startswith('VmRSS:'))
                sample['client_rss_mib'] = int(rss)/1024
                h = get('/health', timeout=5)
                sample.update(health={k:h.get(k) for k in ('ok','fatal','memory','streams','progress','requests_running')})
                if time.monotonic() > next_hosts:
                    sample['available_gib'] = {host:memory(host)['MemAvailable']/2**30 for host in ('head','worker')}
                    next_hosts = time.monotonic() + 10
            except Exception as exc:
                sample['error'] = type(exc).__name__ + ': ' + str(exc)
            record['samples'].append(sample)
            done.wait(2)

    watcher = threading.Thread(target=monitor, daemon=True)
    watcher.start()
    try:
        if args.shared_prefix:
            prime=post(dict(prompt=prompt_ids(args.initial_tokens+args.prime_offset,0),max_tokens=8,
                            ignore_eos=True,temperature=0),'/v1/completions',timeout=1800)
            record['prime']=dict(seconds=prime['seconds'],usage=prime['response'].get('usage'),
                                 tensorfold=prime['response'].get('tensorfold'))
        for cycle in range(args.rounds):
            first_sample = len(record['samples'])
            size = args.initial_tokens + cycle * args.growth
            gate = threading.Barrier(args.streams)
            shared_prompt = None
            if args.mode == 'raw':
                # Same conversations grow; each has a distinct early prefix and
                # a different tail length, exercising shape changes and reuse.
                if args.identical:
                    ids = prompt_ids(size, 0)
                    prompts = [ids]*args.streams
                    shared_prompt = json.dumps(ids, separators=(',', ':')).encode()
                else:
                    prompts = [prompt_ids(size + (i*137 + cycle*53) % 1024,
                                          0 if args.shared_prefix else i)
                               for i in range(args.streams)]
            def request(i):
                if args.mode == 'raw':
                    body = dict(prompt=prompts[i], max_tokens=args.reply_tokens, ignore_eos=True,
                                temperature=1.0, seed=9000+i, return_token_ids=True,
                                **({'draft':False} if args.no_draft else {}))
                    route = '/v1/completions'
                else:
                    lines = ''.join(f'File {i}/record-{j}: value {(j*7919+i*313)%100003}; inspect before editing.\n'
                                    for j in range(max(1,size//23)+(i*17)%51))
                    params = {'type':'object','properties':{'path':{'type':'string'},'line':{'type':'integer'}},
                              'required':['path','line'],'additionalProperties':False}
                    tools = [{'type':'function','function':{'name':'read_file','strict':True,
                              'description':'Inspect one file at a given line.','parameters':params}}]
                    body = dict(messages=[{'role':'system','content':f'You are code review worker {i}. Inspect files with tools.'},
                                          {'role':'user','content':lines+'\nInspect one of the listed files using read_file.'}],
                                tools=tools, tool_choice='required', parallel_tool_calls=False, max_tokens=args.reply_tokens,
                                temperature=1.0, seed=9000+i, chat_template_kwargs={'enable_thinking':True},
                                thinking_budget=32, return_token_ids=True)
                    route = '/v1/chat/completions'
                gate.wait(timeout=60)
                result = post(body, route, timeout=1800, shared_prompt=shared_prompt)
                r = result['response']; tf = dict(r.get('tensorfold',{})); ids = tf.pop('token_ids',None)
                token_ids_sha256 = None
                if args.require_replay_parity:
                    assert isinstance(ids, list) and len(ids) == args.reply_tokens, 'Missing complete token IDs'
                    token_ids_sha256 = hashlib.sha256(json.dumps(ids, separators=(',', ':')).encode()).hexdigest()
                calls = r['choices'][0].get('message',{}).get('tool_calls',[])
                if args.mode == 'tools':
                    assert calls and all(c['function']['name']=='read_file' for c in calls), (
                        'tool call missing',i,r['choices'][0]['finish_reason'],r['usage'])
                    for c in calls:
                        parsed=json.loads(c['function']['arguments']);assert set(parsed)=={'path','line'}, (
                            'incomplete tool arguments',i,r['choices'][0]['finish_reason'],r['usage'])
                    assert tf.get('drafts') is False
                else:
                    assert r['usage']['completion_tokens']==args.reply_tokens
                    if args.no_draft:
                        assert tf.get('drafts') is False
                return dict(case_index=i,seconds=result['seconds'],usage=r.get('usage'),tensorfold=tf,
                            finish=r['choices'][0]['finish_reason'],tool_calls=len(calls),
                            token_ids_sha256=token_ids_sha256)
            t = time.monotonic()
            results, errors = [], []
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.streams) as pool:
                futures = [pool.submit(request,i) for i in range(args.streams)]
                for f in futures:
                    try: results.append(f.result())
                    except Exception as exc: errors.append(type(exc).__name__+': '+str(exc))
            peak = max((s.get('health',{}).get('streams',{}).get('decoding',0)
                        for s in record['samples'][first_sample:]),default=0)
            item = dict(cycle=cycle,seconds=round(time.monotonic()-t,3),results=results,errors=errors,
                        peak_decoding=peak)
            record['cycles'].append(item)
            atomic(path,record)
            if errors: raise RuntimeError(f'{len(errors)} requests failed: {errors[0]}')
            if args.require_concurrency:
                assert peak == args.streams, ('not all full-context sessions decoded together',peak,args.streams)
            if args.require_replay_parity and cycle:
                reference = {r['case_index']: r['token_ids_sha256'] for r in record['cycles'][0]['results']}
                assert all(r['token_ids_sha256'] == reference[r['case_index']] for r in results), (
                    'fixed-seed token IDs changed between identical full-context waves', cycle)
                item['replay_parity_passed'] = True
            h=get('/health');assert h['ok'] and not h['requests_running']
            item['health_after']=h
            atomic(path,record)
            print('cycle',cycle,'passed',round(time.monotonic()-started),'seconds; memory',h.get('memory'),flush=True)
        if args.require_compaction:
            before = record['health_before']['memory'].get('kv_compactions', 0)
            after = get('/health')['memory'].get('kv_compactions', 0)
            assert after > before, 'No KV compaction occurred; this run did not exercise relocation'
            record['compactions_exercised'] = after-before
        record['vision_after']=vision((240,20,20))
        assert 'red' in text(record['vision_after']).lower()
        record.update(status='passed',health_after=get('/health'))
    except BaseException as exc:
        record.update(status='failed',error=type(exc).__name__+': '+str(exc))
        raise
    finally:
        done.set();watcher.join(timeout=30)
        record['finished']=now();record['wall_seconds']=round(time.monotonic()-started,3)
        atomic(path,record)


if __name__=='__main__':
    main()
