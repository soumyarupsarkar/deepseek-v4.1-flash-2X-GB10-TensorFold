"""Bounded mixed-load soak; each cycle leaves the same pair serving."""
import argparse
import concurrent.futures
import json
import re
import time

from common import ROOT, atomic, now
from cluster import get, memory
from qualify import chat, post, vision, text, structured


def main():
    p=argparse.ArgumentParser();p.add_argument('--seconds',type=int,default=360)
    p.add_argument('--streams',type=int,default=16)
    p.add_argument('--record',default='soak');a=p.parse_args()
    assert re.fullmatch('[a-z0-9-]+',a.record)
    record=dict(started=now(),health_before=get('/health'),cycles=[],memory=[])
    assert 3 <= a.streams <= record['health_before']['streams']['max']
    record['parameters']=vars(a)
    path=ROOT/('records/validation-'+a.record+'.json')
    assert not path.exists(), 'Choose a new receipt name; preserve previous qualification.'
    start=time.monotonic()
    try:
        cycle=0
        while time.monotonic()-start<a.seconds:
            # Distinct bodies and lengths exercise fresh Engram reads and prefix
            # admission after earlier streams have released their extents.
            def request(n):
                lines=''.join(f'Record {i}: copper value {(i*7919+n*313)%100003}, label item-{n}-{i}.\n'
                              for i in range(40+(n%4)*65))
                return chat(lines+f'\nSummarize this table in five concise observations. Test cycle {cycle}.')
            with concurrent.futures.ThreadPoolExecutor(max_workers=a.streams) as pool:
                futures=[pool.submit(request,i) for i in range(a.streams-2)]
                futures.append(pool.submit(post,dict(messages=[{'role':'user','content':'Return a JSON object with status ok and a short comment.'}],
                    max_tokens=128,temperature=0,chat_template_kwargs={'enable_thinking':False},
                    response_format={'type':'json_object'})))
                futures.append(pool.submit(vision,(240,20,20) if cycle%2==0 else (20,20,240)))
                results=[f.result() for f in futures]
            assert isinstance(json.loads(text(results[-2])),dict)
            assert ('red' if cycle%2==0 else 'blue') in text(results[-1]).lower()
            h=get('/health');assert h['ok'] and not h['requests_running']
            record['cycles'].append(dict(cycle=cycle,time=now(),health=h,
                requests=[dict(seconds=r['seconds'],usage=r['response'].get('usage'),
                               tensorfold=r['response'].get('tensorfold')) for r in results]))
            record['memory'].append(dict(time=now(),available_gib={h:memory(h)['MemAvailable']/2**30 for h in ('head','worker')}))
            atomic(path,record)
            print('cycle',cycle,'passed; elapsed',round(time.monotonic()-start),'seconds',flush=True)
            cycle+=1
            time.sleep(5)
        record['structured_after']=structured()
        record.update(status='passed',health_after=get('/health'))
    except BaseException as exc:
        record.update(status='failed',error=type(exc).__name__+': '+str(exc),response_body=getattr(exc,'response_body',None))
        raise
    finally:
        record['finished']=now();atomic(path,record)
    print('Mixed-load soak passed',len(record['cycles']),'cycles',flush=True)


if __name__=='__main__':main()
