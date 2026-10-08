"""Measured concurrent decoding and long-context probes, with bounded receipts."""
import argparse
import concurrent.futures
import json
import re
import threading
import time

from common import ROOT, atomic, now
from cluster import get, memory
from qualify import post, chat, text


def prompt_ids(count, stream=0):
    # Render a real chat template; length-adjust only the repeated reference body.
    prefix=post(dict(prompt=f'Reference document {stream}:\n',add_special_tokens=False), '/tokenize')['response']['tokens']
    filler=post(dict(prompt='The copper kettle is on the wooden table.\n',add_special_tokens=False), '/tokenize')['response']['tokens']
    body='Reference notes.\n'+('The copper kettle is on the wooden table.\n'*8)
    rendered=post(dict(messages=[{'role':'user','content':body+'\nWrite a detailed account of the reference notes.'}],
                       chat_template_kwargs={'enable_thinking':False}), '/tokenize')['response']['tokens']
    # The tokenizer's full template tokens remain intact at each end.
    start=rendered[:8]+prefix
    end=rendered[-32:]
    n=count-len(start)-len(end)
    assert n>0
    return start+(filler*((n+len(filler)-1)//len(filler)))[:n]+end


def digest(result):
    r=result['response']
    return dict(seconds=result['seconds'], usage=r.get('usage'), tensorfold=r.get('tensorfold'),
                finish=r['choices'][0]['finish_reason'], sample=r['choices'][0].get('text','')[:240])


def burst(streams, prompt_tokens, reply_tokens, *, no_draft=False):
    prompts=[prompt_ids(prompt_tokens,i) for i in range(streams)]
    gate=threading.Barrier(streams)
    samples=[];monitor_done=threading.Event()
    def poll():
        while not monitor_done.is_set():
            try:
                h=get('/health',timeout=10)
                samples.append(dict(seconds=round(time.monotonic()-started,2),streams=h.get('streams'),
                                    progress=h.get('progress'),running=h.get('requests_running')))
            except OSError:pass
            monitor_done.wait(.5)
    def request(ids):
        gate.wait(timeout=30)
        return post(dict(prompt=ids,max_tokens=reply_tokens,ignore_eos=True,temperature=0,
                         **({'draft':False} if no_draft else {})),
                    '/v1/completions',timeout=3600)
    started=time.monotonic()
    watcher=threading.Thread(target=poll,daemon=True);watcher.start()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=streams) as pool:
            results=list(pool.map(request,prompts))
    finally:
        monitor_done.set();watcher.join(timeout=15)
    for r in results:
        assert r['response']['usage']['prompt_tokens']==prompt_tokens
        assert r['response']['usage']['completion_tokens']==reply_tokens
    peak=max((s['streams']['decoding'] for s in samples if s.get('streams')),default=0)
    return dict(streams=streams,prompt_tokens=prompt_tokens,reply_tokens=reply_tokens,
                wall_seconds=round(time.monotonic()-started,3),peak_decoding=peak,
                results=[digest(r) for r in results],health_samples=samples)


def main():
    p=argparse.ArgumentParser();p.add_argument('--streams',type=int,required=True)
    p.add_argument('--prompt-tokens',type=int,default=2048)
    p.add_argument('--reply-tokens',type=int,default=256)
    p.add_argument('--record',required=True)
    p.add_argument('--no-draft',action='store_true',help='Compare ordinary decoding on the same image/profile')
    p.add_argument('--allow-staggered',action='store_true',help='Record long-prompt overlap without requiring every slot at once')
    p.add_argument('--check-solo',action='store_true',help='Compare the first concurrent reply with the same request run alone')
    a=p.parse_args();assert re.fullmatch('[a-z0-9-]+',a.record)
    result=dict(started=now(),parameters=vars(a),health_before=get('/health'))
    path=ROOT/('records/validation-'+a.record+'.json')
    try:
        result['burst']=burst(a.streams,a.prompt_tokens,a.reply_tokens,no_draft=a.no_draft)
        if not a.allow_staggered:
            assert result['burst']['peak_decoding']==a.streams, ('not all slots observed decoding',result['burst']['peak_decoding'],a.streams)
        if a.check_solo:
            solo=post(dict(prompt=prompt_ids(a.prompt_tokens,0),max_tokens=a.reply_tokens,ignore_eos=True,
                           temperature=0,**({'draft':False} if a.no_draft else {})),'/v1/completions',timeout=3600)
            result['solo']=digest(solo)
            expected=result['burst']['results'][0]['tensorfold']['token_sha']
            assert expected and expected==result['solo']['tensorfold']['token_sha'],'concurrent/solo token hashes differ'
        result['health_after']=get('/health')
        assert result['health_after']['ok'] and not result['health_after']['requests_running']
        result['canary']=chat('Reply with HEALTHY.')
        assert 'HEALTHY' in text(result['canary'])
        result['memory_available_gib']={h:memory(h)['MemAvailable']/2**30 for h in ('head','worker')}
        result['status']='passed'
    except BaseException as exc:
        result.update(status='failed',error=type(exc).__name__+': '+str(exc),
                      response_body=getattr(exc,'response_body',None))
        raise
    finally:
        result['finished']=now();atomic(path,result)
    print(a.record,'passed',result['burst']['wall_seconds'],'seconds',flush=True)


if __name__=='__main__':main()
