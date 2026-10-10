"""Explicit maintenance-window fault tests for the owned pair; leaves it stopped."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

SOURCE=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(SOURCE/'deployment/scripts'))
from configuration import load, read
from runtime import Pair, atomic, now
from cli import check_host


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('test',choices=('interrupted-start','worker-failure'))
    parser.add_argument('--record',required=True)
    parser.add_argument('--config',type=Path,default=SOURCE/'deployment/local.json')
    args=parser.parse_args()
    if not args.record.replace('-','').isalnum():raise ValueError('Use a simple receipt name')
    pair=Pair(load(args.config));pair.ownership()
    path=pair.state/'qualification/records'/('lifecycle-'+args.record+'.json')
    if path.exists():raise ValueError('Preserve previous evidence; choose a new record name')
    receipt=dict(started=now(),test=args.test,status='running')
    atomic(path,receipt);started=time.monotonic()
    try:
        if args.test=='interrupted-start':
            for host in ('head','worker'):
                pair.idle(host)
                if pair.containers(host):raise RuntimeError('Stop both ranks before testing interrupted setup')
            code="""import os,sys
sys.path.insert(0,sys.argv[1])
from configuration import load
from runtime import Pair
p=Pair(load(sys.argv[2]))
with p.lock():
 for h in ('head','worker'):p.apply_display(h)
 os._exit(97) # Simulate controller loss after durable journals, before launch.
"""
            result=subprocess.run([sys.executable,'-B','-c',code,str(SOURCE/'deployment/scripts'),str(args.config)],
                                  capture_output=True,text=True,timeout=180)
            receipt['interrupted_exit_code']=result.returncode
            receipt['journals_survived']=all(read(pair.state/('drm-'+h+'.json'))['active'] for h in ('head','worker'))
            # Always try restoration, including a partially failed injection.
            with pair.lock():pair.stop()
            if result.returncode!=97 or not receipt['journals_survived']:
                raise RuntimeError('Interruption injection failed: '+result.stderr[-2000:])
        else:
            health=pair.get('/health')
            if not health.get('ok') or health.get('requests_running') or health.get('busy'):
                raise RuntimeError('An idle healthy pair is required before killing its owned worker')
            expected=read(pair.state/'launch.json')
            rows={h:pair.containers(h) for h in ('head','worker')}
            if any(len(r)!=1 or not r[0]['State']['Running'] or r[0]['Id']!=expected['containers'][h]
                   for h,r in rows.items()):raise RuntimeError('Owned rank identity differs')
            receipt['before']=dict(health=health,containers=expected['containers'],image=expected['image'])
            atomic(path,receipt)
            pair.docker('worker','kill','--signal','KILL',rows['worker'][0]['Id'],timeout=30)
            deadline=time.monotonic()+180
            while time.monotonic()<deadline:
                if (not any(pair.containers(h) for h in ('head','worker'))
                        and all(not read(pair.state/('drm-'+h+'.json'))['active'] for h in ('head','worker'))):
                    break
                time.sleep(2)
            else:raise TimeoutError('Paired monitor did not finish cleanup and restoration')
            receipt['monitor_fault']=read(pair.state/'fault.json')
        with pair.lock():check_host(pair)
        receipt.update(status='passed',restoration=read(pair.state/'restoration-check.json'))
    except BaseException as exc:
        receipt.update(status='failed',error=type(exc).__name__+': '+str(exc))
        raise
    finally:
        receipt.update(finished=now(),seconds=round(time.monotonic()-started,3))
        atomic(path,receipt)
    print(args.test,'passed in',receipt['seconds'],'seconds; pair remains stopped',flush=True)


if __name__=='__main__':main()
