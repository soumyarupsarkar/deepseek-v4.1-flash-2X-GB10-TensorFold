"""Fill extent reservations with short prompts, then release one and verify queue progress.

This tests aggregate admission, not the throughput of eight fully prefetched long
contexts: each live request reserves its maximum prompt/reply extent but is
cancelled after a few output tokens.
"""
import argparse
import concurrent.futures
import json
import re
import threading
import time
import urllib.request

from common import ROOT, atomic, now
from cluster import get
from qualify import BASE, MODEL, OPENER, post, chat, text


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--record',default='pool-queue')
    parser.add_argument('--allow-fragmentation',action='store_true',
                        help='After prior cache use, validate queued progress even when fewer full extents fit')
    args=parser.parse_args();assert re.fullmatch('[a-z0-9-]+',args.record)
    initial=get('/health');capacity=initial['capacity']
    context=capacity['per_request_tokens'];holders=capacity['shared_pool_tokens']//context
    assert initial['streams']['max']>holders>=2
    count=holders+1
    first=[threading.Event() for _ in range(count)]
    release=[threading.Event() for _ in range(count)]
    prefixes=['' for _ in range(count)]
    record=dict(started=now(),health_before=initial,reserved_requests=holders,admission_samples=[])
    def request(i):
        body=dict(model=MODEL,messages=[{'role':'user','content':f'Test {i}: count upwards with detailed explanations.'}],
                  chat_template_kwargs={'enable_thinking':False},temperature=0,ignore_eos=True,stream=True)
        tokens=post({k:v for k,v in body.items() if k not in ('model','stream')},'/tokenize')['response']['count']
        body['max_tokens']=context-tokens
        req=urllib.request.Request(BASE+'/v1/chat/completions',data=json.dumps(body).encode(),
                                   headers={'Content-Type':'application/json'})
        with OPENER.open(req,timeout=90) as response:
            for line in response:
                if line.startswith(b'data:') and b'[DONE]' not in line:
                    chunk=json.loads(line[5:].strip())
                    prefixes[i]+=''.join(c.get('delta',{}).get('content') or '' for c in chunk.get('choices',[]))
                    if len(prefixes[i])>=128:
                        first[i].set()
                        assert release[i].wait(120),'holder was not explicitly released'
                        return
        raise AssertionError('stream ended before its first token')
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
            futures=[]
            try:
                futures=[pool.submit(request,i) for i in range(holders)]
                deadline=time.monotonic()+30
                while not all(x.is_set() for x in first[:holders]) and time.monotonic()<deadline:
                    h=get('/health')
                    record['admission_samples'].append(dict(streams=h['streams'],
                        running=h['requests_running'],ready=[i for i in range(holders) if first[i].is_set()]))
                    time.sleep(.5)
                active=[i for i in range(holders) if first[i].is_set()]
                record['actual_holders']=len(active)
                record['fragmentation_observed']=len(active)<holders
                if len(active)<holders:
                    assert args.allow_fragmentation,('not all full extents fit',active,holders)
                    assert active,'no full-context reservation made progress'
                    queued=next(i for i in range(holders) if i not in active)
                else:
                    queued=holders
                    futures.append(pool.submit(request,queued))
                    time.sleep(3)
                record['full']=get('/health')
                assert record['full']['streams']['decoding']==len(active)
                assert not first[queued].is_set(),'queued request unexpectedly started before release'
                record['queued_index']=queued;record['released_index']=active[0]
                release[active[0]].set()
                assert first[queued].wait(20),'queued request did not progress after a full extent was released'
                record['after_release']=get('/health')
            finally:
                for signal in release:signal.set()
                for future in futures:future.result(timeout=100)
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            final=get('/health')
            if not final['requests_running']:break
            time.sleep(.25)
        assert final['ok'] and not final['requests_running']
        prefixes=prefixes[:len(futures)]
        record['prefixes_at_full_extent_offsets']=prefixes
        record['solo_checks']=[]
        for i,prefix in enumerate(prefixes):
            assert len(prefix)>=128,('missing reply prefix',i)
            solo=chat(f'Test {i}: count upwards with detailed explanations.')
            assert text(solo).startswith(prefix),('full-extent offset changed the reply prefix',i)
            record['solo_checks'].append(dict(index=i,prefix_equal=True,seconds=solo['seconds']))
        record['canary']=chat('Reply with HEALTHY.')
        assert 'HEALTHY' in text(record['canary'])
        record.update(status='passed',health_after=get('/health'))
    except BaseException as exc:
        record.update(status='failed',error=type(exc).__name__+': '+str(exc))
        raise
    finally:
        record['finished']=now();atomic(ROOT/('records/validation-'+args.record+'.json'),record)
    print('Full-pool queuing, release and healthy follow-up passed',flush=True)


if __name__=='__main__':main()
