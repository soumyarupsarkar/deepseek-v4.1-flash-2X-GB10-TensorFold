"""Repeatable API qualification; receipts describe exactly what was exercised."""
import argparse
import base64
import concurrent.futures
import hashlib
import json
import re
import struct
import time
import urllib.error
import urllib.request
import zlib

from common import ROOT, atomic, now
from cluster import get, memory

from common import API_BASE as BASE
MODEL = 'DeepSeek-V4.1-Flash-Keys'
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def post(body, route='/v1/chat/completions', timeout=1200, *, shared_prompt=None):
    body = dict(model=MODEL, **body)
    headers = {'Content-Type':'application/json'}
    if shared_prompt is None:
        data = json.dumps(body).encode()
    else:
        # Qualification clients run on the head too. Share an identical long
        # prompt's immutable bytes across requests, as the benchmark does.
        body.pop('prompt')
        metadata = json.dumps(body, separators=(',', ':')).encode()
        data = (b'{"prompt":', shared_prompt, b','+metadata[1:])
        headers['Content-Length'] = str(sum(map(len, data)))
    req = urllib.request.Request(BASE + route, data=data, headers=headers)
    start = time.monotonic()
    try:
        with OPENER.open(req, timeout=timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        exc.response_body = exc.read().decode(errors='replace')
        raise
    return dict(seconds=round(time.monotonic()-start, 3), response=result)

def chat(text, **kw):
    return post(dict(messages=[{'role':'user','content':text}], max_tokens=96,
                     temperature=0, chat_template_kwargs={'enable_thinking':False}, return_token_ids=True, **kw))

def text(result):
    return result['response']['choices'][0]['message'].get('content') or ''

def png(color):
    def chunk(kind, raw):
        return struct.pack('!I',len(raw))+kind+raw+struct.pack('!I',zlib.crc32(kind+raw)&0xffffffff)
    width=height=256
    # A large colored square on a white border: two images with identical token layouts.
    rows=[]
    for y in range(height):
        rows.append(b'\0'+b''.join(bytes(color if 24<=x<232 and 24<=y<232 else (255,255,255))
                                   for x in range(width)))
    raw=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!IIBBBBB',width,height,8,2,0,0,0))
    raw+=chunk(b'IDAT',zlib.compress(b''.join(rows)))+chunk(b'IEND',b'')
    return 'data:image/png;base64,'+base64.b64encode(raw).decode()

def vision(color):
    return post(dict(messages=[{'role':'user','content':[
        {'type':'text','text':'What color is the large square? Answer with just the color name.'},
        {'type':'image_url','image_url':{'url':png(color)}}]}],
        max_tokens=32, temperature=0, chat_template_kwargs={'enable_thinking':False}))

def stream_post(body):
    request=urllib.request.Request(BASE+'/v1/chat/completions',data=json.dumps(dict(model=MODEL,stream=True,
                                   stream_options={'include_usage':True},**body)).encode(),
                                   headers={'Content-Type':'application/json'})
    chunks=[];content=[];reasoning=[];calls={};stats={};finish=None
    start=time.monotonic()
    with OPENER.open(request,timeout=1200) as response:
        for line in response:
            if not line.startswith(b'data:'):continue
            raw=line[5:].strip()
            if raw==b'[DONE]':break
            part=json.loads(raw);chunks.append(part)
            stats.update(part.get('tensorfold',{}))
            for choice in part.get('choices',[]):
                delta=choice.get('delta',{})
                content.append(delta.get('content') or '')
                reasoning.append(delta.get('reasoning_content') or '')
                finish=choice.get('finish_reason') or finish
                for call in delta.get('tool_calls',[]):
                    row=calls.setdefault(call['index'],{'name':'','arguments':''})
                    for k,v in call.get('function',{}).items():
                        if k in row:row[k]+=v
    return dict(seconds=round(time.monotonic()-start,3),content=''.join(content),reasoning=''.join(reasoning),
                calls=list(calls.values()),finish=finish,tensorfold=stats,chunks=len(chunks))

def structured():
    out={'started':now(),'health_before':get('/health')}
    schema={'type':'object','properties':{'status':{'type':'string','enum':['ok']},
                                        'value':{'type':'integer','const':42}},
            'required':['status','value'],'additionalProperties':False}
    base=dict(messages=[{'role':'user','content':'Return status ok and value 42 as JSON.'}],
              max_tokens=256,temperature=0,chat_template_kwargs={'enable_thinking':False},
              response_format={'type':'json_schema','json_schema':{'name':'answer','strict':True,'schema':schema}})
    out['schema']=post(base)
    assert json.loads(text(out['schema']))=={'status':'ok','value':42}
    assert out['schema']['response']['tensorfold']['drafts'] is False
    out['json_object']=post({**base,'response_format':{'type':'json_object'}})
    assert isinstance(json.loads(text(out['json_object'])),dict)
    out['schema_stream']=stream_post(base)
    assert json.loads(out['schema_stream']['content'])=={'status':'ok','value':42}
    out['thinking_schema']=post({**base,'chat_template_kwargs':{'enable_thinking':True},'thinking_budget':16})
    assert json.loads(text(out['thinking_schema']))=={'status':'ok','value':42}
    params={'type':'object','properties':{'city':{'type':'string','enum':['Seattle']},
                                        'days':{'type':'integer','enum':[3]}},
            'required':['city','days'],'additionalProperties':False}
    tools=[{'type':'function','function':{'name':'weather','description':'Get a weather forecast.',
                                         'strict':True,'parameters':params}}]
    tool_body=dict(messages=[{'role':'user','content':'Use weather to get the forecast for Seattle for 3 days.'}],
                   tools=tools,tool_choice={'type':'function','function':{'name':'weather'}},
                   parallel_tool_calls=False,max_tokens=256,temperature=0,
                   chat_template_kwargs={'enable_thinking':False})
    out['tool_named']=post(tool_body)
    calls=out['tool_named']['response']['choices'][0]['message']['tool_calls']
    assert len(calls)==1 and calls[0]['function']['name']=='weather'
    assert json.loads(calls[0]['function']['arguments'])=={'city':'Seattle','days':3}
    assert out['tool_named']['response']['tensorfold']['drafts'] is False
    out['tool_auto']=post({**tool_body,'tool_choice':'auto'})
    calls=out['tool_auto']['response']['choices'][0]['message']['tool_calls']
    assert len(calls)==1 and calls[0]['function']['name']=='weather'
    assert json.loads(calls[0]['function']['arguments'])=={'city':'Seattle','days':3}
    assert out['tool_auto']['response']['tensorfold']['drafts'] is False
    out['auto_without_call']=post({**tool_body,'tool_choice':'auto',
        'messages':[{'role':'user','content':'What is 19 + 23? Reply with only the answer and do not use a tool.'}]})
    assert '42' in text(out['auto_without_call'])
    assert not out['auto_without_call']['response']['choices'][0]['message'].get('tool_calls')
    out['tool_stream']=stream_post({**tool_body,'tool_choice':'required'})
    assert len(out['tool_stream']['calls'])==1 and out['tool_stream']['calls'][0]['name']=='weather'
    assert json.loads(out['tool_stream']['calls'][0]['arguments'])=={'city':'Seattle','days':3}
    out['tool_thinking']=post({**tool_body,'chat_template_kwargs':{'enable_thinking':True},'thinking_budget':16})
    calls=out['tool_thinking']['response']['choices'][0]['message']['tool_calls']
    assert json.loads(calls[0]['function']['arguments'])=={'city':'Seattle','days':3}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        jobs=[pool.submit(post,base),pool.submit(chat,'Write a short haiku about a copper kettle.'),
              pool.submit(post,tool_body),pool.submit(chat,'List the first ten prime numbers.')]
        out['mixed']=[job.result() for job in jobs]
    assert [r['response']['tensorfold']['drafts'] for r in out['mixed']]==[False,True,False,True]
    try:
        post({**base,'response_format':{'type':'json_schema','json_schema':{'schema':{'type':'invalid-type'}}}})
    except urllib.error.HTTPError as exc:
        out['invalid_schema_status']=exc.code
        assert exc.code==400,exc.code
    else:raise AssertionError('malformed schema was not refused')
    out['after_invalid']=chat('Reply with HEALTHY.')
    assert 'HEALTHY' in text(out['after_invalid'])
    out['health_after']=get('/health')
    assert out['health_after']['ok'] and not out['health_after']['requests_running']
    out.update(finished=now(),status='passed')
    return out

def baseline():
    out={'started':now(), 'models':get('/v1/models'), 'health_before':get('/health')}
    out['arithmetic']=chat('What is 19 + 23? Reply with just the number.')
    assert '42' in text(out['arithmetic']),text(out['arithmetic'])
    prompt='Write a short Python function that returns the sum of the even numbers in a list.'
    out['drafted']=chat(prompt,draft=True)
    out['serial']=chat(prompt,draft=False)
    a=out['drafted']['response'].get('tensorfold',{})
    b=out['serial']['response'].get('tensorfold',{})
    # Prefer the engine's token ids; text equality remains an API-level check.
    assert text(out['drafted'])==text(out['serial']), 'draft/serial replies differ'
    if a.get('token_ids') is not None and b.get('token_ids') is not None:
        assert a['token_ids']==b['token_ids'],'draft/serial token IDs differ'
    out['vision_red']=vision((240,20,20)); out['vision_blue']=vision((20,20,240))
    assert 'red' in text(out['vision_red']).lower(),text(out['vision_red'])
    assert 'blue' in text(out['vision_blue']).lower(),text(out['vision_blue'])
    reference='Reference table:\n'+''.join(f'Item {i:04d}: label amber, category eight, number {i%97}.\n'
                                            for i in range(500))
    out['prefix_first']=chat(reference+'\nReply with READY.')
    out['prefix_reuse']=chat(reference+'\nReply with READY and the first item number.')
    usage=out['prefix_reuse']['response']['usage']
    assert usage.get('prompt_tokens_details',{}).get('cached_tokens',0)>0,usage
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        start=time.monotonic()
        out['four_streams']=list(pool.map(lambda n:chat(f'Write ten concise facts about the number {n}.'),
                                          (11,13,17,19)))
        out['four_stream_wall_seconds']=round(time.monotonic()-start,3)
    out['health_after']=get('/health')
    assert out['health_after']['ok'] and not out['health_after']['requests_running']
    out['memory_available_gib']={h:memory(h)['MemAvailable']/2**30 for h in ('head','worker')}
    out.update(finished=now(),status='passed')
    return out

def main():
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['baseline','structured'])
    parser.add_argument('--record',default=None)
    args=parser.parse_args()
    name=args.record or args.stage
    if not re.fullmatch('[a-z0-9-]+',name):raise ValueError('Invalid receipt name')
    record=ROOT/('records/validation-'+name+'.json')
    try:
        result=baseline() if args.stage=='baseline' else structured()
    except Exception as exc:
        atomic(ROOT/('records/validation-'+name+'-failure.json'),
               dict(time=now(),error=type(exc).__name__+': '+str(exc),
                    response_body=getattr(exc,'response_body',None)))
        raise
    atomic(record,result)
    print(args.stage,'passed; receipt:',record,flush=True)

if __name__=='__main__':
    main()
