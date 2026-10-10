"""Thirty-two distinct synthetic prefixes: cold admission, replay and extensions."""
import argparse,concurrent.futures,hashlib,json,pathlib,sys,time
SOURCE=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(SOURCE/'tools/qualification'))
import common,cluster
from benchmark import normalize_health,evict,prompt,tokens,digest
original_get=cluster.get
cluster.get=lambda path,**kw: normalize_health(original_get(path,**kw)) if path=='/health' else original_get(path,**kw)
from qualify import post,BASE
from engine_health import ready
from configuration import profile
p=argparse.ArgumentParser();p.add_argument('--record',required=True);p.add_argument('--prefix-tokens',type=int,default=16384);a=p.parse_args()
assert a.record.replace('-','').isalnum() and a.prefix_tokens>=4096
assert common.PAIR.config['api']['bind']=='127.0.0.1'
path=common.ROOT/'records'/('validation-'+a.record+'.json');assert not path.exists()
record=dict(started=common.now(),status='running',stages=[],prefix_tokens=a.prefix_tokens,streams=32,
            script_sha256=hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest())
common.atomic(path,record)
def ask(ids):
 r=post(dict(prompt=ids,max_tokens=16,ignore_eos=True,temperature=0,draft=False),'/v1/completions',timeout=3600)
 v=r['response'];u=v['usage'];assert u['prompt_tokens']==len(ids) and u['completion_tokens']==16
 return dict(seconds=r['seconds'],prompt_sha256=digest(ids),usage=u,cached=u['prompt_tokens_details']['cached_tokens'],token_sha=v['tensorfold']['token_sha'])
def stage(name,rows):
 h=original_get('/health');assert ready(h,profile()) and h['scheduler']['running']==0
 assert h['native']['retained_states']<=64
 assert h['native']['snapshot_bytes']<=512*2**20
 record['stages'].append(dict(name=name,rows=rows,health=h));common.atomic(path,record)
 print(name,'passed; retained states',h['native']['retained_states'],flush=True)
try:
 record['health_before']=original_get('/health');assert ready(record['health_before'],profile())
 record['eviction']=evict(BASE,190000)
 ids=[prompt(BASE,a.prefix_tokens,290000+i,'code')[0] for i in range(32)]
 with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:cold=list(pool.map(ask,ids))
 assert all(r['cached']==0 for r in cold)
 stage('32-distinct-cold-prefixes',cold)
 warm=[ask(x) for x in ids]
 assert all(r['cached']>=a.prefix_tokens-2048 for r in warm),[r['cached'] for r in warm]
 assert [r['token_sha'] for r in warm]==[r['token_sha'] for r in cold]
 stage('32-sequential-replays',warm)
 suffix=tokens(BASE,text=' Continue with another small example and explanation. ')
 suffix=(suffix*((512+len(suffix)-1)//len(suffix)))[:512]
 continued=[x+suffix for x in ids]
 first=[ask(x) for x in continued]
 assert all(r['cached']>=a.prefix_tokens-2048 for r in first)
 stage('32-sequential-extensions',first)
 again=[ask(x) for x in continued]
 assert all(r['cached']>=a.prefix_tokens for r in again)
 assert [r['token_sha'] for r in again]==[r['token_sha'] for r in first]
 stage('32-extended-replays',again)
 record['status']='passed'
except BaseException as exc:
 record.update(status='failed',error=type(exc).__name__+': '+str(exc),response_body=getattr(exc,'response_body',None));raise
finally:
 record['finished']=common.now();common.atomic(path,record)
