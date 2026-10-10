"""Cold synthetic greedy/stochastic parity across ordinary and drafted waves."""
import argparse,hashlib,json,pathlib,sys
SOURCE=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(SOURCE/'tools/qualification'))
import common,cluster
from benchmark import wave
from engine_health import ready
from configuration import profile
p=argparse.ArgumentParser();p.add_argument('--record',required=True)
p.add_argument('--streams',type=int,nargs='+',default=[4,8,16,24,32]);p.add_argument('--temperature',type=float,default=0)
a=p.parse_args();assert a.record.replace('-','').isalnum()
assert common.PAIR.config['api']['bind']=='127.0.0.1'
path=common.ROOT/'records'/('validation-'+a.record+'.json');assert not path.exists()
h=cluster.get('/health');assert ready(h,profile()) and h['scheduler']['running']==0
record=dict(started=common.now(),parameters=vars(a),health_before=h,status='running',waves=[],
    script_sha256=hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest())
common.atomic(path,record)
try:
 for index,streams in enumerate(a.streams):
  comparison={}
  for mode in (('ordinary','default') if index%2==0 else ('default','ordinary')):
   case=dict(streams=streams,prompt_tokens=1024,reply_tokens=256,mode=mode,cache='cold',
             temperature=a.temperature,seed=733001,prompt_class='code')
   row=wave(common.API_BASE,case,310000+2*index+len(comparison))
   assert row['summary']['peak_decoding']==streams
   if mode=='default':assert row['summary']['drafted']>0,'Drafted mode did not exercise drafting'
   comparison[mode]=row;record['waves'].append(row);common.atomic(path,record)
   print('C'+str(streams),mode,'passed',row['summary']['aggregate_e2e_tps'],'e2e tok/s',flush=True)
  left,right=(comparison[m]['results'] for m in ('ordinary','default'))
  assert all(x['prompt_sha256']==y['prompt_sha256'] and x['tensorfold']['token_sha']==y['tensorfold']['token_sha']
             for x,y in zip(left,right)),'Drafted/ordinary token parity changed'
  comparison['default']['all_token_hashes_match_ordinary']=True;common.atomic(path,record)
 record.update(status='passed',health_after=cluster.get('/health'))
except BaseException as exc:
 record.update(status='failed',error=type(exc).__name__+': '+str(exc))
 if hasattr(exc,'benchmark_wave'):record['failing_wave']=exc.benchmark_wave
 raise
finally:
 record['finished']=common.now();common.atomic(path,record)
