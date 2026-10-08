"""Request cancellation, malformed input and idle recovery without a rank restart."""
import argparse
import json
import re
import time
import urllib.error
import urllib.request

from common import ROOT, atomic, now
from cluster import get
from qualify import BASE, MODEL, OPENER, post, chat, text


def cancel(constrained=False):
    body=dict(model=MODEL,stream=True,messages=[{'role':'user','content':'Count from 1 to 5000 with an explanation of each number.'}],
              max_tokens=2048,temperature=0,chat_template_kwargs={'enable_thinking':False})
    if constrained:
        body.update(messages=[{'role':'user','content':'Produce a JSON array containing the numbers 1 through 5000.'}],
                    response_format={'type':'json_schema','json_schema':{'name':'numbers','strict':True,
                         'schema':{'type':'array','items':{'type':'integer'},'minItems':32}}})
    request=urllib.request.Request(BASE+'/v1/chat/completions',data=json.dumps(body).encode(),
                                   headers={'Content-Type':'application/json'})
    start=time.monotonic();seen=0
    with OPENER.open(request,timeout=120) as response:
        for line in response:
            if line.startswith(b'data:') and b'[DONE]' not in line:
                part=json.loads(line[5:].strip())
                if any(c.get('delta',{}).get('content') for c in part.get('choices',[])):
                    seen+=1
                    if seen>=3:break
    assert seen==3
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        h=get('/health')
        if not h['requests_running']:break
        time.sleep(.25)
    assert h['ok'] and not h['requests_running'],h
    reply=chat('Reply with HEALTHY.')
    assert 'HEALTHY' in text(reply)
    return dict(constrained=constrained,closed_after_content_chunks=seen,
                recovered_seconds=round(time.monotonic()-start,3),health=h,canary=reply)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--record',default='recovery')
    args=parser.parse_args();assert re.fullmatch('[a-z0-9-]+',args.record)
    result=dict(started=now(),health_before=get('/health'))
    try:
        result['cancel_plain']=cancel()
        result['cancel_schema']=cancel(True)
        context=result['health_before']['context_length']
        try:
            post(dict(prompt=[1000]*(context+1),max_tokens=1),'/v1/completions')
        except urllib.error.HTTPError as exc:
            result['over_context_status']=exc.code
            assert exc.code==400
        else:raise AssertionError('over-context request accepted')
        # An actual quiet interval, followed by a new grammar request, exercises
        # the previous deployment's idle-to-busy failure pattern.
        time.sleep(45)
        result['after_idle']=post(dict(messages=[{'role':'user','content':'Reply with JSON status ok.'}],max_tokens=64,
            temperature=0,chat_template_kwargs={'enable_thinking':False},response_format={'type':'json_object'}))
        assert isinstance(json.loads(text(result['after_idle'])),dict)
        result['health_after']=get('/health');assert result['health_after']['ok']
        result['status']='passed'
    except BaseException as exc:
        result.update(status='failed',error=type(exc).__name__+': '+str(exc),response_body=getattr(exc,'response_body',None))
        raise
    finally:
        result['finished']=now();atomic(ROOT/('records/validation-'+args.record+'.json'),result)
    print('cancellation, invalid context, idle recovery passed',flush=True)


if __name__=='__main__':main()
