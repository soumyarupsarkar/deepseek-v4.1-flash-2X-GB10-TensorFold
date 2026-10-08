"""Compare ordinary and speculative C16/C24/C32 decoding with verified cold prefixes.

Only synthetic prompts are sent. Distinct completed prompts evict the configured
retained-prefix cache between waves. Each measured wave must report
zero cached tokens; token hashes must match for every stream across modes.
"""
import argparse
import json
import re
import threading
import time

from common import ROOT, atomic, now
from cluster import get, memory
from qualify import BASE, post
from qualify_capacity import identities
from qualify_pool import burst
from benchmark import evict as evict_prefixes


def evict(cycle):
    return evict_prefixes(BASE, 100000+cycle)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--record',required=True)
    parser.add_argument('--streams',type=int,nargs='+',default=[16,24,32,32])
    args=parser.parse_args()
    assert re.fullmatch('[a-z0-9-]+',args.record)
    path=ROOT/('records/validation-'+args.record+'.json')
    assert not path.exists(),'Preserve prior measurements'
    before=get('/health')
    assert before['ok'] and not before['requests_running']
    record=dict(started=now(),parameters=vars(args),health_before=before,
                launch=json.loads((ROOT/'records/launch.json').read_text()),
                hosts=identities(),waves=[],samples=[],status='running')
    started=time.monotonic()
    done=threading.Event()
    stage={'name':'setup'}

    def observe():
        next_print=0
        while not done.is_set():
            sample=dict(seconds=round(time.monotonic()-started,2),stage=stage['name'])
            try:
                h=get('/health',timeout=5)
                sample['health']={k:h.get(k) for k in ('ok','fatal','memory','streams','progress')}
                sample['available_gib']={host:memory(host)['MemAvailable']/2**30 for host in ('head','worker')}
                if sample['seconds']>=next_print:
                    print(stage['name'],sample['seconds'],h.get('streams'),sample['available_gib'],flush=True)
                    next_print=sample['seconds']+45
            except Exception as exc:
                sample['error']=type(exc).__name__+': '+str(exc)
            record['samples'].append(sample)
            done.wait(5)

    watcher=threading.Thread(target=observe,daemon=True);watcher.start()
    try:
        cycle=0
        for index,streams in enumerate(args.streams):
            comparison={}
            modes=('ordinary','drafts') if index%2==0 else ('drafts','ordinary')
            for mode in modes:
                stage['name']=f'C{streams}-{mode}-evict'
                eviction=evict(cycle);cycle+=1
                assert identities()==record['hosts'],'inference pair changed'
                h=get('/health')
                stage['name']=f'C{streams}-{mode}'
                result=burst(streams,1024,256,no_draft=mode=='ordinary')
                after=get('/health')
                cached=sum(r['usage'].get('prompt_tokens_details',{}).get('cached_tokens',0)
                           for r in result['results'])
                delta_cached=after['cached_tokens_total']-h['cached_tokens_total']
                assert cached==delta_cached==0,('prefix cache confounds comparison',cached,delta_cached)
                assert result['peak_decoding']==streams
                assert after['ok'] and not after['requests_running']
                assert after['memory']['allocation_ooms']==0
                row=dict(index=index,streams=streams,mode=mode,eviction=eviction,burst=result,health_after=after,
                         cached_tokens=cached,drafted=after['drafted_total']-h['drafted_total'],
                         accepted=after['accepted_total']-h['accepted_total'],
                         output_tokens_per_second=streams*256/result['wall_seconds'])
                record['waves'].append(row)
                comparison[mode]=row
                atomic(path,record)
                print(stage['name'],'passed',result['wall_seconds'],'s',row['output_tokens_per_second'],'tokens/s',flush=True)
            a,b=(comparison[m]['burst']['results'] for m in ('ordinary','drafts'))
            assert all(x['tensorfold']['token_sha']==y['tensorfold']['token_sha'] for x,y in zip(a,b)), 'token parity'
            comparison['drafts']['all_reply_hashes_match_ordinary']=True
            atomic(path,record)
        assert identities()==record['hosts']
        record.update(status='passed',health_after=get('/health'))
    except BaseException as exc:
        record.update(status='failed',error=type(exc).__name__+': '+str(exc))
        raise
    finally:
        done.set();watcher.join(timeout=30)
        record.update(finished=now(),seconds=round(time.monotonic()-started,3))
        atomic(path,record)


if __name__=='__main__':main()
