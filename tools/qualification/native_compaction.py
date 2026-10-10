"""Fragment live reservations, require relocation, and compare continued replies.

This exercises address relocation and cancellation, not long-context throughput.
The optional partial-prefill gate gives one holder a cold 262k prompt and requires
its populated extent to move before its first reply token.
"""
import argparse,concurrent.futures,hashlib,json,pathlib,sys,threading,time,urllib.request
SOURCE=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(SOURCE/'tools/qualification'))
import common,cluster
from qualify import BASE,MODEL,OPENER,post,chat,text
from engine_health import ready
from configuration import profile
p=argparse.ArgumentParser();p.add_argument('--record',required=True)
p.add_argument('--partial-prefill',action='store_true');a=p.parse_args()
assert a.record.replace('-','').isalnum()
assert common.PAIR.config['api']['bind']=='127.0.0.1'
path=common.ROOT/'records'/('validation-'+a.record+'.json');assert not path.exists()
record=dict(started=common.now(),status='running',health_before=cluster.get('/health'),samples=[],
            partial_prefill=a.partial_prefill,
            script_sha256=hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest())
assert ready(record['health_before'],profile()) and record['health_before']['scheduler']['running']==0
common.atomic(path,record)
count=17
first=[threading.Event() for _ in range(count)]
control=[threading.Event() for _ in range(count)]
cancel=[False]*count
prefixes=['']*count
prompts=[]
for i in range(count):
    prompt=post(dict(messages=[{'role':'user','content':f'Synthetic relocation test {i}. Count upwards from 1, explaining each number in a sentence.'}],
        chat_template_kwargs={'enable_thinking':False}),'/tokenize')['response']['tokens']
    prompts.append(prompt)
if a.partial_prefill:
    from benchmark import prompt as synthetic_prompt
    prompts[1],_=synthetic_prompt(BASE,262144,2026101110,'code')

def h():
    value=cluster.get('/health');assert ready(value,profile()),'Native pair unhealthy'
    record['samples'].append(dict(time=common.now(),native=value['native'],scheduler=value['scheduler']))
    return value

def request(i):
    limit=524288 if i<16 else 1048576
    body=dict(model=MODEL,prompt=prompts[i],max_tokens=limit-len(prompts[i]),
              ignore_eos=True,temperature=0,draft=False,stream=True)
    req=urllib.request.Request(BASE+'/v1/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
    pieces=0
    with OPENER.open(req,timeout=600 if a.partial_prefill else 240) as response:
        for line in response:
            if not line.startswith(b'data:'):continue
            raw=line[5:].strip()
            if raw==b'[DONE]':break
            part=json.loads(raw)
            assert 'error' not in part,part.get('error')
            piece=''.join(choice.get('text') or '' for choice in part.get('choices',[]))
            if not piece:continue
            prefixes[i]+=piece;pieces+=1
            if pieces==24:
                first[i].set()
                assert control[i].wait(180),'Coordinator did not release holder'
                if cancel[i]:return dict(index=i,cancelled=True,pieces=pieces)
            if pieces==64:return dict(index=i,cancelled=True,pieces=pieces)
    raise AssertionError('Holder ended before coordinator cancellation')

def wait_first(i,future,timeout=90):
    deadline=time.monotonic()+timeout
    while not first[i].is_set() and time.monotonic()<deadline:
        if future.done():future.result();raise AssertionError('Holder ended early')
        h();time.sleep(.2)
    assert first[i].is_set(),('holder failed to start',i)

try:
    with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
        jobs={}
        try:
            # Sequential admission makes alternating releases fragment the layout.
            for i in range(16):
                fed=h()['native']['prefill_tokens']
                jobs[i]=pool.submit(request,i)
                if i==1 and a.partial_prefill:
                    deadline=time.monotonic()+60
                    while time.monotonic()<deadline:
                        value=h()
                        if value['native']['prefilling_streams']==1 and value['native']['prefill_tokens']>=fed+2048:break
                        if jobs[i].done():jobs[i].result();raise AssertionError('Partial holder ended early')
                        time.sleep(.2)
                    assert value['native']['prefilling_streams']==1 and value['native']['prefill_tokens']>=fed+2048
                    assert not first[i].is_set(),'Holder was no longer prefilling'
                    record['partial_holder_started']=value
                else:
                    wait_first(i,jobs[i])
            record['full']=h();assert record['full']['native']['active_streams']==16
            common.atomic(path,record)
            for i in range(0,16,2):cancel[i]=True;control[i].set()
            for i in range(0,16,2):jobs[i].result(timeout=30)
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                value=h()
                if value['native']['active_streams']==8:break
                time.sleep(.25)
            assert value['native']['active_streams']==8
            record['fragmented']=value
            if a.partial_prefill:
                assert value['native']['prefilling_streams']==1 and not first[1].is_set()
            jobs[16]=pool.submit(request,16);wait_first(16,jobs[16])
            record['relocated']=h()
            assert record['relocated']['native']['compactions']>value['native']['compactions'],'Workload did not exercise live compaction'
            assert record['relocated']['native']['relocated_tokens']>value['native']['relocated_tokens']
            if a.partial_prefill:
                assert record['relocated']['native']['relocated_prefills']>value['native']['relocated_prefills'], \
                    'Workload did not move a populated partial prefill'
                assert not first[1].is_set(),'Partial holder finished prefill before relocation evidence'
            common.atomic(path,record)
            for i in list(range(1,16,2))+[16]:control[i].set()
            if a.partial_prefill:wait_first(1,jobs[1],timeout=600)
            record['holders']=[future.result(timeout=60) for future in jobs.values()]
        finally:
            for i in range(count):cancel[i]=True;control[i].set()
            for future in jobs.values():
                try:future.result(timeout=120)
                except Exception:pass
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        value=h()
        if value['scheduler']['running']==0 and value['scheduler']['waiting']==0:break
        time.sleep(.25)
    assert value['scheduler']['running']==0 and value['scheduler']['waiting']==0
    record['solo_comparisons']=[]
    for i in list(range(1,16,2))+[16]:
        solo=post(dict(prompt=prompts[i],max_tokens=256,ignore_eos=True,temperature=0,draft=False),'/v1/completions')
        answer=solo['response']['choices'][0]['text']
        assert answer.startswith(prefixes[i]),('Relocated stream differs from solo',i)
        record['solo_comparisons'].append(dict(index=i,prefix_equal=True,characters=len(prefixes[i]),
            prefix_sha256=hashlib.sha256(prefixes[i].encode()).hexdigest(),solo_token_sha=solo['response']['tensorfold']['token_sha']))
        common.atomic(path,record)
    canary=chat('Reply with HEALTHY.');assert 'HEALTHY' in text(canary)
    record.update(status='passed',health_after=h(),canary=canary)
except BaseException as exc:
    record.update(status='failed',error=type(exc).__name__+': '+str(exc),response_body=getattr(exc,'response_body',None));raise
finally:
    record['finished']=common.now();common.atomic(path,record)
print('Live compaction, continued reply parity and cancellation passed',flush=True)
