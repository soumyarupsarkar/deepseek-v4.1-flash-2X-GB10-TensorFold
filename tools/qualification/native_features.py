"""Native API qualification adapter. Synthetic fixtures only; no service changes."""
import argparse,concurrent.futures,hashlib,json,pathlib,sys,urllib.error,urllib.request
SOURCE=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(SOURCE/'tools/qualification'))
import common,cluster
from benchmark import normalize_health,wait_idle
raw_get=cluster.get
cluster.get=lambda path,**kw: normalize_health(raw_get(path,**kw)) if path=='/health' else raw_get(path,**kw)
import qualify as q
from engine_health import ready
from configuration import profile

def post(body,route='/v1/chat/completions'):
 body=dict(body);body.setdefault('model',q.MODEL)
 req=urllib.request.Request(common.API_BASE+route,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
 try:
  with q.OPENER.open(req,timeout=1200) as r:return json.load(r)
 except urllib.error.HTTPError as exc:
  exc.response_body=exc.read().decode(errors='replace');raise

def content(r):return r['choices'][0]['message'].get('content') or ''
def seed(r):return int(r['tensorfold']['sampling_seed'])
def sha(r):return r['tensorfold']['token_sha']
def simple(text,**kw):return dict(messages=[{'role':'user','content':text}],max_tokens=96,temperature=0,chat_template_kwargs={'enable_thinking':False},**kw)

def aliases():
 data=raw_get('/v1/models')['data'];names={r['id']:r['max_model_len'] for r in data}
 results={}
 for suffix,limit in [('262k',262144),('524k',524288),('614k',614400),('1m',1048576)]:
  name=q.MODEL+'-'+suffix;assert names[name]==limit
  r=post(simple('What is 19 + 23? Reply with just the number.',model=name));assert '42' in content(r)
  results[name]=dict(response=r,limit=limit)
  try:post(dict(simple('Reply OK.',model=name),max_tokens=limit+1))
  except urllib.error.HTTPError as exc:assert exc.code==400;results[name]['over_limit_status']=exc.code
  else:raise AssertionError('Alias accepted a request over its context limit')
 return dict(models=data,checks=results)

def protocols():
 body=simple('What is 19 + 23? Reply with just the number.')
 r=post(dict(model=q.MODEL,input='What is 19 + 23? Reply with just the number.',temperature=0,
             max_output_tokens=64,chat_template_kwargs={'enable_thinking':False}),'/v1/responses')
 assert r['object']=='response'
 text=''.join(c.get('text','') for item in r['output'] for c in item.get('content',[]))
 assert '42' in text,r
 m=post(dict(body,max_tokens=64,thinking={'type':'disabled'}),'/v1/messages')
 assert m['type']=='message' and '42' in ''.join(c.get('text','') for c in m['content'])
 stream=q.stream_post(body);single=post(body)
 assert stream['tensorfold']['token_sha']==sha(single)
 return dict(responses=r,messages=m,stream=stream,single=single)

def sampling():
 body=dict(simple('Invent three unusual names for a tiny bookstore on a moon. Return only the three names.'),temperature=1,return_token_ids=True)
 out={};out['unseeded']=[post(body) for _ in range(4)];out['null_seed']=post(dict(body,seed=None))
 seeds=[seed(r) for r in out['unseeded']+[out['null_seed']]]
 assert all(0<=s<2**64 for s in seeds) and len(set(seeds))==len(seeds)
 out['returned_seed_replay']=post(dict(body,seed=str(seeds[0])))
 assert sha(out['returned_seed_replay'])==sha(out['unseeded'][0])
 fixed=dict(body,seed=0);out['zero']=post(fixed);out['ordinary']=post(dict(fixed,draft=False))
 assert seed(out['zero'])==0 and sha(out['zero'])==sha(out['ordinary'])
 out['stream']=q.stream_post(fixed);assert out['stream']['tensorfold']['sampling_seed']=='0'
 assert out['stream']['tensorfold']['token_sha']==sha(out['zero'])
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:out['concurrent']=list(pool.map(lambda _:post(fixed),range(4)))
 assert all(seed(r)==0 and sha(r)==sha(out['zero']) for r in out['concurrent'])
 out['greedy']=[post(dict(body,temperature=0)) for _ in range(2)]
 assert all(r['tensorfold']['sampling_seed'] is None for r in out['greedy'])
 assert sha(out['greedy'][0])==sha(out['greedy'][1])
 out['native_seed_contract']='random unseeded u64; prompt-derived 63-bit rule retained; explicit seed bits unchanged'
 return out

parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['baseline','structured','sampling','aliases','protocols']);parser.add_argument('--record',required=True);args=parser.parse_args()
assert args.record.replace('-','').isalnum()
path=common.ROOT/'records'/('validation-'+args.record+'.json');assert not path.exists(),'Preserve prior receipts'
assert common.PAIR.config['api']['bind']=='127.0.0.1','Qualification endpoint must be isolated'
before=raw_get('/health');assert ready(before,profile()) and before['scheduler']['running']==0
record=dict(started=common.now(),stage=args.stage,status='running',health_before=before,source_script_sha256=hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest())
common.atomic(path,record)
try:
 if args.stage=='structured':record['result']=q.structured(drafts=True)
 elif args.stage=='baseline':record['result']=q.baseline()
 else:record['result']=globals()[args.stage]()
 after,drain=wait_idle(common.API_BASE);assert ready(after,profile()) and after['scheduler']['running']==0
 record.update(status='passed',health_after=after,post_response_drain=drain)
except BaseException as exc:
 record.update(status='failed',error=type(exc).__name__+': '+str(exc),response_body=getattr(exc,'response_body',None));raise
finally:
 record['finished']=common.now();common.atomic(path,record)
print(args.stage,'passed; receipt:',path,flush=True)
